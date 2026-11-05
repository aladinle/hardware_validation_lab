"""M2A business rules. This module queues work; it never executes a workload."""
from dataclasses import asdict, dataclass
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.http import Http404
from django.utils import timezone
from contracts.v1 import ContractError, manifest, parse_submission
from contracts.plugins import executable_manifest, validate_manifest, validate_parameters
from .access import scope
from .models import (Artifact, Batch, Device, DeviceGrant, Job, Membership, Project, Role, Run,
                     ServicePrincipal, ServiceToken, TestApproval, TestDefinition, TestGrant, TestVersion, User)
from .services import audit, digest


class Rejected(Exception):
    def __init__(self, code, message, status=400):
        self.code, self.message, self.status = code, message, status


@dataclass(frozen=True)
class Actor:
    user_id: int
    principal_id: object = None
    token_id: object = None


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def checksum(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def locked_scope(actor, project_id, *, manager=False):
    # Consistent lock order: requester user -> project. Project mutations share this lock.
    user = User.objects.select_for_update().get(pk=actor.user_id)
    if not user.is_active:
        raise Rejected("UNAUTHENTICATED", "Account is inactive.", 401)
    project = Project.objects.select_for_update().filter(pk=project_id).first()
    if project is None:
        raise Http404
    project, role, member = scope(user, project.pk)
    if manager and (actor.principal_id or role != Role.ADMIN):
        raise Rejected("FORBIDDEN", "Project administrator access required.", 403)
    principal = None
    if actor.principal_id:
        principal = ServicePrincipal.objects.filter(pk=actor.principal_id, owner=user, project=project, active=True).first()
        token = ServiceToken.objects.filter(pk=actor.token_id, principal=principal, revoked_at=None, expires_at__gt=timezone.now()).first()
        if principal is None or token is None:
            raise Rejected("UNAUTHENTICATED", "Service credential unavailable.", 401)
    return user, project, role, member, principal


def current_member(user, project):
    # Even a platform administrator needs explicit execution grants for submission.
    return Membership.objects.filter(user=user, project=project, active=True).first()


def artifact_visible(actor, artifact, user, role):
    if actor.principal_id:
        return artifact.principal_id == actor.principal_id
    return role == Role.ADMIN or artifact.owner_id == user.pk


@transaction.atomic
def publish(actor, project_id, definition_id, *, workload_wheel=None):
    user, project, role, member, principal = locked_scope(actor, project_id)
    definition = TestDefinition.objects.filter(pk=definition_id, project=project).first()
    if definition is None:
        raise Http404
    if actor.principal_id or role not in {Role.ADMIN, Role.ENGINEER} or (role == Role.ENGINEER and definition.created_by_id != user.pk):
        raise Rejected("FORBIDDEN", "Only an authorized author can publish this draft.", 403)
    content = manifest(definition.draft_header_bytes)
    if workload_wheel is not None:
        # Only the trusted local management command supplies a wheel. Existing
        # browser/API publication retains metadata-only semantics.
        from workloads.registry import verify_wheel
        content = executable_manifest(definition.draft_header_bytes, verify_wheel(workload_wheel))
    latest = definition.versions.order_by("-number").first()
    version = TestVersion.objects.create(definition=definition, number=latest.number + 1 if latest else 1,
                                         manifest=content, manifest_sha256=checksum(content), created_by=user)
    audit(user, project, "version.published", version.pk)
    return version


@transaction.atomic
def edit_draft(actor, project_id, payload, definition_id=None):
    user, project, role, member, principal = locked_scope(actor, project_id)
    if actor.principal_id or role not in {Role.ADMIN, Role.ENGINEER}:
        raise Rejected("FORBIDDEN", "Draft authoring requires an engineer or administrator.", 403)
    if set(payload) != {"name", "header_bytes"} or not isinstance(payload["name"], str) or not 1 <= len(payload["name"].strip()) <= 120:
        raise ContractError("Provide name (1-120 characters) and header_bytes.")
    manifest(payload["header_bytes"])
    if definition_id:
        definition = TestDefinition.objects.filter(pk=definition_id, project=project).first()
        if definition is None:
            raise Http404
        if role == Role.ENGINEER and definition.created_by_id != user.pk:
            raise Rejected("FORBIDDEN", "You can edit only your own draft.", 403)
        definition.name, definition.draft_header_bytes = payload["name"].strip(), payload["header_bytes"]
        definition.save(update_fields=["name", "draft_header_bytes"])
    else:
        definition = TestDefinition.objects.create(project=project, created_by=user, name=payload["name"].strip(), draft_header_bytes=payload["header_bytes"])
    audit(user, project, "draft.saved", definition.pk)
    return definition


@transaction.atomic
def approval(actor, project_id, version_id, approved):
    user, project, *_ = locked_scope(actor, project_id, manager=True)
    version = TestVersion.objects.filter(pk=version_id, definition__project=project).first()
    if version is None:
        raise Http404
    if approved:
        TestApproval.objects.get_or_create(version=version, revoked_at=None, defaults={"approved_by": user})
    else:
        TestApproval.objects.filter(version=version, revoked_at=None).update(revoked_at=timezone.now())
    audit(user, project, "approval.granted" if approved else "approval.revoked", version.pk)


@transaction.atomic
def version_grant(actor, project_id, member_id, version_id, granted):
    user, project, *_ = locked_scope(actor, project_id, manager=True)
    member = Membership.objects.filter(pk=member_id, project=project).first()
    version = TestVersion.objects.filter(pk=version_id, definition__project=project).first()
    if member is None or version is None:
        raise Http404
    query = {"membership": member, "version": version, "test": version.definition}
    if granted:
        TestGrant.objects.get_or_create(**query)
    else:
        TestGrant.objects.filter(**query).delete()
    audit(user, project, "version_grant.changed", f"{member.pk}:{version.pk}:{granted}")


@transaction.atomic
def submit(actor, key, payload):
    request = parse_submission(payload)
    if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", key):
        raise ContractError("Idempotency-Key must contain 1-128 letters, digits, dots, underscores, colons or hyphens.")
    user, project, role, member, principal = locked_scope(actor, request.project_id)
    member = current_member(user, project)
    if member is None or member.role not in {Role.ADMIN, Role.ENGINEER, Role.OPERATOR}:
        raise Rejected("FORBIDDEN", "An active permitted execution membership is required.", 403)
    validated = []
    for index, item in enumerate(request.items, 1):
        version = TestVersion.objects.filter(pk=item.version_id, definition__project=project).first()
        device = Device.objects.filter(pk=item.device_id, project=project).first()
        if version is None or device is None:
            raise Rejected("FORBIDDEN_RESOURCE", f"Item {index} has an unavailable test or device.", 403)
        if not device.enabled:
            raise Rejected("FORBIDDEN_DEVICE", f"Item {index} device is disabled.", 403)
        if not TestGrant.objects.filter(membership=member, version=version, test=version.definition).exists():
            raise Rejected("FORBIDDEN_TEST", f"Item {index} needs an explicit grant for this version.", 403)
        if not TestApproval.objects.filter(version=version, revoked_at=None).exists():
            raise Rejected("UNAPPROVED_VERSION", f"Item {index} does not have a current test approval.", 403)
        if not DeviceGrant.objects.filter(membership=member, device=device).exists():
            raise Rejected("FORBIDDEN_DEVICE", f"Item {index} needs a device grant.", 403)
        if principal and (not principal.versions.filter(pk=version.pk).exists() or not principal.devices.filter(pk=device.pk).exists()):
            raise Rejected("FORBIDDEN_SERVICE_SCOPE", f"Item {index} is outside this service scope.", 403)
        spec, declared = validate_manifest(version.manifest)
        if not set(spec.capabilities) <= set(device.capabilities):
            raise Rejected("NO_MATCHING_CAPABILITY", f"Item {index} has no matching device capability.")
        validate_parameters(spec.name, item.parameters, declared_header=declared)
        inputs = []
        for artifact_id in (item.expected_artifact_id, item.actual_artifact_id):
            artifact = Artifact.objects.filter(pk=artifact_id, project=project).first()
            if artifact is None or not artifact_visible(actor, artifact, user, role):
                raise Rejected("FORBIDDEN_INPUT", f"Item {index} has an unavailable input artifact.", 403)
            # Verify stored input integrity, not merely possession of a metadata ID.
            read_input(artifact)
            inputs.append(artifact)
        validated.append((item, version, device, *inputs))
    request_hash = checksum(asdict(request))
    requester_key = f"service:{principal.pk}" if principal else f"user:{user.pk}"
    existing = Batch.objects.filter(requester_key=requester_key, idempotency_key=key).first()
    if existing:
        if existing.request_sha256 != request_hash:
            raise Rejected("IDEMPOTENCY_CONFLICT", "This key was already used for different request content.", 409)
        return existing, False
    batch = Batch.objects.create(project=project, requester=user, principal=principal, requester_key=requester_key,
                                 idempotency_key=key, request_sha256=request_hash)
    for item, version, device, expected, actual in validated:
        snapshot = {"schema_version": 1, "test_version_id": str(version.pk), "test_name": version.definition.name,
                    "manifest": version.manifest, "manifest_sha256": version.manifest_sha256,
                    "device_id": str(device.pk), "device_name": device.name, "device_source": device.source,
                    "device_capabilities": device.capabilities, "firmware": None, "hardware_revision": None,
                    "software_commit": request.software_commit, "agent_version": None, "environment": None,
                    "parameters": item.parameters, "inputs": {"expected": expected.sha256, "actual": actual.sha256},
                    "requester_id": user.pk, "service_principal_id": str(principal.pk) if principal else None}
        job = Job.objects.create(batch=batch, version=version, device=device, expected=expected, actual=actual,
                                 parameters=item.parameters, snapshot=snapshot, queue_deadline=timezone.now() + timedelta(seconds=request.queue_seconds))
        Run.objects.create(job=job)
    audit(user, project, "batch.queued", batch.pk)
    return batch, True


def artifact_path(artifact_id):
    root = Path(settings.ARTIFACT_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    for part in (root, *root.parents):
        info = part.lstat()
        if part.is_symlink() or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024):
            raise Rejected("ARTIFACT_STORE_UNAVAILABLE", "Artifact store path is unsafe.", 503)
    return root / f"{artifact_id}.bin"


def read_input(artifact):
    path = artifact_path(artifact.pk)
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or path.is_symlink() or getattr(info, "st_file_attributes", 0) & 1024:
            raise OSError
        with path.open("rb") as stream:
            data = stream.read(settings.MAX_INPUT_BYTES + 1)
    except OSError as exc:
        raise Rejected("ARTIFACT_UNAVAILABLE", "Input evidence is unavailable.", 503) from exc
    if len(data) != artifact.size or hashlib.sha256(data).hexdigest() != artifact.sha256:
        raise Rejected("ARTIFACT_CONFLICT", "Stored input checksum or size does not match.", 409)
    return data


@transaction.atomic
def upload(actor, project_id, name, declared_hash, data):
    user, project, role, member, principal = locked_scope(actor, project_id)
    if role not in {Role.ADMIN, Role.ENGINEER, Role.OPERATOR}:
        raise Rejected("FORBIDDEN", "This role cannot upload inputs.", 403)
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}", name):
        raise ContractError("Use a simple input filename, without directories.")
    if not 1 <= len(data) <= settings.MAX_INPUT_BYTES:
        raise Rejected("INPUT_SIZE_LIMIT", "Inputs must contain 1 byte to 1 MiB.", 413)
    actual_hash = hashlib.sha256(data).hexdigest()
    if declared_hash != actual_hash:
        raise Rejected("ARTIFACT_CONFLICT", "Input checksum does not match.", 409)
    # M2A stores CAN text input only, never executable uploads. Detailed parsing is M2B.
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ContractError("CAN fixture input must be ASCII text.") from exc
    if any(ord(c) < 32 and c not in "\r\n\t" for c in text):
        raise ContractError("Input contains unsupported control characters.")
    duplicate = Artifact.objects.filter(project=project, owner=user, principal=principal, sha256=actual_hash, name=name, size=len(data)).first()
    if duplicate:
        read_input(duplicate)
        return duplicate, False
    artifact = Artifact(project=project, owner=user, principal=principal, name=name, sha256=actual_hash, size=len(data))
    path = artifact_path(artifact.pk)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        artifact.save(force_insert=True)
        audit(user, project, "input.uploaded", artifact.pk)
    except BaseException:
        path.unlink(missing_ok=True)  # This call owns this generated file; never a client path.
        raise
    return artifact, True


@transaction.atomic
def rotate_token(actor, project_id, principal_id):
    user, project, *_ = locked_scope(actor, project_id, manager=True)
    principal = ServicePrincipal.objects.filter(pk=principal_id, project=project, active=True).first()
    if principal is None:
        raise Http404
    ServiceToken.objects.filter(principal=principal, revoked_at=None).update(revoked_at=timezone.now())
    secret = secrets.token_urlsafe(32)
    token = ServiceToken.objects.create(principal=principal, digest=digest(secret), expires_at=timezone.now() + timedelta(days=7))
    audit(user, project, "service_token.rotated", token.pk)
    return secret, token


@transaction.atomic
def revoke_invitation(actor, project_id, invitation_id):
    from .models import Invitation
    user, project, *_ = locked_scope(actor, project_id, manager=True)
    invitation = Invitation.objects.filter(pk=invitation_id, project=project).first()
    if invitation is None:
        raise Http404
    Invitation.objects.filter(pk=invitation.pk).update(revoked_at=timezone.now())
    audit(user, project, "invitation.revoked", invitation.pk)


@transaction.atomic
def account_access(actor, target_id, action):
    # Only platform administrators may change global accounts/sessions.
    administrator = User.objects.filter(pk=actor.user_id, is_active=True).first()
    if administrator is None or actor.principal_id or not administrator.is_superuser:
        raise Rejected("FORBIDDEN", "Platform administrator access required.", 403)
    target = User.objects.select_for_update().filter(pk=target_id).first()
    if target is None:
        raise Http404
    if target.pk == administrator.pk or target.is_superuser:
        raise Rejected("FORBIDDEN", "Use a separately reviewed local procedure for platform administrators.", 403)
    if action not in {"deactivate", "reactivate", "revoke_sessions"}:
        raise ContractError("Unsupported account action.")
    target.session_epoch += 1
    if action != "revoke_sessions":
        target.is_active = action == "reactivate"
    target.save(update_fields=["session_epoch", "is_active"])
    if action == "deactivate":
        from .models import Invitation
        Invitation.objects.filter(created_by=target, consumed_at=None, revoked_at=None).update(revoked_at=timezone.now())
        ServicePrincipal.objects.filter(owner=target).update(active=False)
        ServiceToken.objects.filter(principal__owner=target, revoked_at=None).update(revoked_at=timezone.now())
    audit(administrator, None, f"account.{action}", target.pk)
