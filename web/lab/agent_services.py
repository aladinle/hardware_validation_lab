"""Agent identity management and idle contact only. No assignment/dispatch side effects."""
from datetime import timedelta
import secrets
from django.db import transaction
from django.http import Http404
from django.utils import timezone
from contracts.agents_v1 import ids, parse_enrollment, parse_heartbeat, text
from .access import scope
from .models import Agent, AgentCredential, AgentDevice, AgentEnrollment, AgentHeartbeat, Device, Role
from .services import audit, digest
from .submissions import Rejected, checksum, locked_scope


def device_scope(agent):
    bindings = list(AgentDevice.objects.filter(agent=agent, active=True).select_related("device"))
    if not 1 <= len(bindings) <= 20 or any(not link.device.enabled or link.device.project_id != agent.project_id for link in bindings):
        raise Rejected("DEVICE_SCOPE_UNAVAILABLE", "Agent device scope is unavailable.", 403)
    return tuple(sorted(str(link.device_id) for link in bindings))


def credential_document(agent, secret, expires, kind):
    return {"schema_version": 1, "agent_id": str(agent.pk), "project_id": str(agent.project_id),
            "device_ids": list(device_scope(agent)), "token": secret, "expires_at": expires.isoformat(), "credential_kind": kind}


def invalidate(agent):
    now = timezone.now()
    AgentCredential.objects.filter(agent=agent, revoked_at=None).update(revoked_at=now)
    AgentEnrollment.objects.filter(agent=agent, revoked_at=None, consumed_at=None).update(revoked_at=now)


def issue_enrollment(agent, issuer):
    invalidate(agent)
    secret = "hve_" + secrets.token_urlsafe(32)
    expires = timezone.now() + timedelta(minutes=15)
    AgentEnrollment.objects.create(agent=agent, issued_by=issuer, digest=digest(secret), expires_at=expires)
    agent.enrolled_at = None
    agent.save(update_fields=["enrolled_at"])
    audit(issuer, agent.project, "agent.enrollment_issued", agent.pk)
    return credential_document(agent, secret, expires, "enrollment")


def bind_devices(agent, device_ids):
    identifiers = ids(device_ids)
    devices = list(Device.objects.filter(pk__in=identifiers, project=agent.project, enabled=True))
    if len(devices) != len(identifiers):
        raise Rejected("DEVICE_SCOPE_UNAVAILABLE", "Provide enabled inventory from this project.", 403)
    if AgentDevice.objects.filter(device__in=devices, active=True).exclude(agent=agent).exists():
        raise Rejected("DEVICE_SCOPE_CONFLICT", "An inventory device is already bound to another agent.", 409)
    AgentDevice.objects.filter(agent=agent).update(active=False)
    for device in devices:
        AgentDevice.objects.update_or_create(agent=agent, device=device, defaults={"active": True})


@transaction.atomic
def create_agent(actor, project_id, name, device_ids):
    user, project, *_ = locked_scope(actor, project_id, manager=True)
    agent = Agent.objects.create(project=project, name=text(name), created_by=user)
    bind_devices(agent, device_ids)
    audit(user, project, "agent.created", agent.pk)
    return agent, issue_enrollment(agent, user)


@transaction.atomic
def manage_agent(actor, project_id, agent_id, action, device_ids=None):
    user, project, *_ = locked_scope(actor, project_id, manager=True)
    agent = Agent.objects.select_for_update().filter(pk=agent_id, project=project).first()
    if agent is None:
        raise Http404
    if action == "disable":
        invalidate(agent)
        agent.enabled = False
        agent.save(update_fields=["enabled"])
    elif action == "revoke":
        invalidate(agent)
    elif action in {"reenroll", "set_devices"}:
        if action == "set_devices":
            bind_devices(agent, device_ids)
        agent.enabled = True
        agent.save(update_fields=["enabled"])
        result = issue_enrollment(agent, user)
        audit(user, project, "agent.scope_changed" if action == "set_devices" else "agent.reenrollment", agent.pk)
        return result
    elif action == "rotate":
        if not agent.enabled or agent.enrolled_at is None:
            raise Rejected("AGENT_UNAVAILABLE", "Enroll an enabled agent before rotating its credential.", 409)
        device_scope(agent)
        invalidate(agent)
        secret, expires = new_credential(agent)
        audit(user, project, "agent.credential_rotated", agent.pk)
        return credential_document(agent, secret, expires, "agent")
    else:
        raise Rejected("INVALID_INPUT", "Unsupported agent action.")
    audit(user, project, "agent.disabled" if action == "disable" else "agent.credentials_revoked", agent.pk)
    return {"status": "updated", "agent_id": str(agent.pk)}


def new_credential(agent):
    secret = "hva_" + secrets.token_urlsafe(32)
    expires = timezone.now() + timedelta(days=7)
    AgentCredential.objects.create(agent=agent, digest=digest(secret), expires_at=expires)
    return secret, expires


def authenticate_agent(agent_id, raw, *, enrolling=False):
    # Called inside a transaction. Match the manager lock order (project -> agent).
    # Opaque digest lookup rejects cookie, CI and wrong-agent credentials alike.
    model = AgentEnrollment if enrolling else AgentCredential
    prefix = "hve_" if enrolling else "hva_"
    if not isinstance(raw, str) or not raw.startswith(prefix) or len(raw) != 47:
        raise Rejected("UNAUTHENTICATED", "Invalid agent credential.", 401)
    candidate = model.objects.filter(agent_id=agent_id, digest=digest(raw)).select_related("agent").first()
    if candidate is None:
        raise Rejected("UNAUTHENTICATED", "Invalid agent credential.", 401)
    from .models import Project
    Project.objects.select_for_update().get(pk=candidate.agent.project_id)
    agent = Agent.objects.select_for_update().get(pk=agent_id)
    credential = model.objects.select_for_update().get(pk=candidate.pk)
    if not agent.enabled or credential.revoked_at or credential.expires_at <= timezone.now():
        raise Rejected("UNAUTHENTICATED", "Agent credential is expired or unavailable.", 401)
    if enrolling:
        if credential.consumed_at or agent.enrolled_at:
            raise Rejected("UNAUTHENTICATED", "Enrollment is unavailable.", 401)
        issuer = credential.issued_by
        try:
            if not issuer.is_active or scope(issuer, agent.project_id)[1] != Role.ADMIN:
                raise Http404
        except Http404 as exc:
            raise Rejected("UNAUTHENTICATED", "Enrollment authority was revoked.", 401) from exc
    elif agent.enrolled_at is None:
        raise Rejected("UNAUTHENTICATED", "Agent is not enrolled.", 401)
    device_scope(agent)
    return agent, credential


@transaction.atomic
def enroll(agent_id, token, payload):
    agent, ticket = authenticate_agent(agent_id, token, enrolling=True)
    request = parse_enrollment(payload)
    if request.device_ids != device_scope(agent):
        raise Rejected("DEVICE_SCOPE_UNAVAILABLE", "Enrollment device scope does not match.", 403)
    ticket.consumed_at = timezone.now()
    ticket.save(update_fields=["consumed_at"])
    agent.enrolled_at = timezone.now()
    agent.reported_platform, agent.reported_version = request.platform, request.agent_version
    agent.save(update_fields=["enrolled_at", "reported_platform", "reported_version"])
    secret, expires = new_credential(agent)
    audit(None, agent.project, "agent.enrolled", agent.pk)
    return credential_document(agent, secret, expires, "agent")


@transaction.atomic
def heartbeat(agent_id, token, payload):
    agent, credential = authenticate_agent(agent_id, token)
    request = parse_heartbeat(payload)
    if request.device_ids != device_scope(agent):
        raise Rejected("DEVICE_SCOPE_UNAVAILABLE", "Heartbeat device scope does not match.", 403)
    body_hash = checksum(payload)
    old = AgentHeartbeat.objects.filter(agent=agent, heartbeat_id=request.heartbeat_id).first()
    if old and old.body_sha256 != body_hash:
        raise Rejected("HEARTBEAT_CONFLICT", "Heartbeat ID was already used with different content.", 409)
    if not old:
        received = AgentHeartbeat.objects.create(agent=agent, heartbeat_id=request.heartbeat_id, body_sha256=body_hash)
        agent.last_contact_at = received.received_at
        agent.reported_platform, agent.reported_version = request.platform, request.agent_version
        agent.save(update_fields=["last_contact_at", "reported_platform", "reported_version"])
        # Bounded contact history; audit/security records are not pruned here.
        keep = list(AgentHeartbeat.objects.filter(agent=agent).order_by("-received_at", "-pk").values_list("pk", flat=True)[:1000])
        AgentHeartbeat.objects.filter(agent=agent).exclude(pk__in=keep).delete()
    return {"schema_version": 1, "agent_id": str(agent.pk), "heartbeat_id": request.heartbeat_id,
            "server_time": timezone.now().isoformat(), "last_contact_at": agent.last_contact_at.isoformat(),
            "replayed": old is not None, "assignment": None, "execution_available": False,
            "devices_connected": [], "ready": False}
