import hashlib
import hmac
import secrets
from datetime import timedelta
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import F
from django.http import Http404
from django.utils import timezone
from .access import scope
from .models import AuditEvent, Invitation, LoginBucket, Membership, Role


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def audit(actor, project, action, target=""):
    AuditEvent.objects.create(actor=actor, project=project, action=action, target=str(target))


@transaction.atomic
def invite(actor, project, email, role):
    if scope(actor, project.pk)[1] != Role.ADMIN:
        raise PermissionError
    token = secrets.token_urlsafe(32)
    Invitation.objects.create(project=project, email=email.lower(), role=role, token_hash=digest(token),
                              expires_at=timezone.now() + timedelta(hours=24), created_by=actor)
    audit(actor, project, "invitation.created", email.lower())
    return token


@transaction.atomic
def accept_invite(token, password):
    invitation = Invitation.objects.select_for_update().get(token_hash=digest(token))
    if invitation.consumed_at or invitation.revoked_at or invitation.expires_at <= timezone.now():
        raise ValueError("Invalid invitation")
    # A revoked inviter cannot keep issuing authority through old invitation links.
    try:
        inviter_role = scope(invitation.created_by, invitation.project_id)[1]
    except (Http404, Membership.DoesNotExist) as exc:
        raise ValueError("Invalid invitation") from exc
    if inviter_role != Role.ADMIN:
        raise ValueError("Invalid invitation")
    claimed = Invitation.objects.filter(pk=invitation.pk, consumed_at=None, revoked_at=None).update(consumed_at=timezone.now())
    if not claimed:
        raise ValueError("Invalid invitation")
    user = get_user_model().objects.create_user(username=invitation.email, email=invitation.email, password=password)
    Membership.objects.create(project=invitation.project, user=user, role=invitation.role)
    audit(user, invitation.project, "invitation.accepted", user.pk)
    return user


@transaction.atomic
def throttled(request, identity, purpose="login"):
    """Database-backed fixed windows. Never trust a client-supplied forwarded IP."""
    now = timezone.now()
    blocked = False
    for kind, value, limit in [("account", identity.strip().lower(), 5), ("ip", request.META.get("REMOTE_ADDR", "unknown"), 30)]:
        key = hmac.new(settings.SECRET_KEY.encode(), f"{purpose}:{kind}:{value}".encode(), hashlib.sha256).hexdigest()
        bucket, _ = LoginBucket.objects.get_or_create(key=key, defaults={"started_at": now})
        LoginBucket.objects.filter(pk=bucket.pk, started_at__lte=now - timedelta(minutes=10)).update(started_at=now, count=0)
        LoginBucket.objects.filter(pk=bucket.pk).update(count=F("count") + 1)
        bucket.refresh_from_db()
        blocked |= bucket.count > limit
    return blocked
