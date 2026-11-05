"""Versioned JSON API. Session clients keep CSRF; bearer clients never fall back to sessions."""
from functools import wraps
import json
from uuid import UUID
from django.core.exceptions import RequestDataTooBig, ValidationError
from django.db import DatabaseError, transaction
from django.http import Http404, HttpResponse, JsonResponse
from django.middleware.csrf import CsrfViewMiddleware
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from contracts.v1 import ContractError, exact_keys, identifier
from .access import records
from .models import (Artifact, Batch, Device, Job, Membership, Role, ServicePrincipal, ServiceToken,
                     TestApproval, TestDefinition, TestVersion)
from .services import audit, digest
from .submissions import (Actor, Rejected, account_access, approval, artifact_visible, edit_draft, locked_scope,
                          publish, read_input, revoke_invitation, rotate_token, submit, upload, version_grant)


def error(code, message, status):
    response = JsonResponse({"schema_version": 1, "error": {"code": code, "message": message}}, status=status)
    if status == 401:
        response["WWW-Authenticate"] = "Bearer"
    return response


def api_view(methods):
    def decorate(function):
        @csrf_exempt
        @wraps(function)
        def wrapped(request, *args, **kwargs):
            try:
                authorization = request.headers.get("Authorization")
                if authorization is not None:
                    if not authorization.startswith("Bearer ") or len(authorization) > 200:
                        raise Rejected("UNAUTHENTICATED", "Invalid credential.", 401)
                    token = ServiceToken.objects.select_related("principal__owner").filter(digest=digest(authorization[7:]), revoked_at=None, expires_at__gt=timezone.now(), principal__active=True, principal__owner__is_active=True).first()
                    if token is None:
                        raise Rejected("UNAUTHENTICATED", "Invalid or expired credential.", 401)
                    if not Membership.objects.filter(user=token.principal.owner, project=token.principal.project, active=True).exclude(role=Role.VIEWER).exists():
                        raise Rejected("UNAUTHENTICATED", "Service owner access is unavailable.", 401)
                    actor = Actor(token.principal.owner_id, token.principal_id, token.pk)
                else:
                    if not request.user.is_authenticated:
                        raise Rejected("UNAUTHENTICATED", "Sign in or provide a scoped bearer token.", 401)
                    rejected = CsrfViewMiddleware(lambda req: HttpResponse()).process_view(request, lambda req: None, (), {})
                    if rejected:
                        return error("CSRF_FAILED", "Reload the form and submit a valid CSRF token.", 403)
                    actor = Actor(request.user.pk)
                if request.method not in methods:
                    response = error("METHOD_NOT_ALLOWED", "Unsupported request method.", 405)
                    response["Allow"] = ", ".join(methods)
                    return response
                with transaction.atomic():
                    return function(request, actor, *args, **kwargs)
            except Rejected as exc:
                return error(exc.code, exc.message, exc.status)
            except (ContractError, ValidationError, ValueError, TypeError, json.JSONDecodeError):
                return error("INVALID_INPUT", "Invalid or unsupported request fields. See the v1 contract.", 400)
            except RequestDataTooBig:
                return error("INPUT_SIZE_LIMIT", "Request size limit exceeded.", 413)
            except Http404:
                return error("NOT_FOUND", "Record unavailable.", 404)
        return wrapped
    return decorate


def body(request):
    if request.content_type != "application/json":
        raise ContractError("Use application/json.")
    if len(request.body) > 65536:
        raise RequestDataTooBig
    # Reject duplicate keys and non-finite numbers instead of hashing ambiguous JSON.
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ContractError("Duplicate JSON key.")
            result[key] = value
        return result
    value = json.loads(request.body, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ContractError()))
    if not isinstance(value, dict):
        raise ContractError("Expected an object.")
    return value


def boolean(value):
    if type(value) is not bool:
        raise ContractError("Expected a boolean.")
    return value


def version_data(version):
    return {"id": str(version.pk), "number": version.number, "manifest": version.manifest,
            "manifest_sha256": version.manifest_sha256,
            "approved": TestApproval.objects.filter(version=version, revoked_at=None).exists()}


def job_data(job):
    return {"schema_version": 1, "id": str(job.pk), "run_id": str(job.run.pk), "batch_id": str(job.batch_id),
            "state": job.state, "outcome": None, "execution_available": False,
            "queue_deadline": job.queue_deadline.isoformat(), "queue_deadline_elapsed": job.queue_deadline <= timezone.now(),
            "created_at": job.created_at.isoformat(), "snapshot": job.snapshot}


def visible_jobs(actor, user, project, role, member):
    query = Job.objects.filter(batch__project=project).select_related("batch", "run")
    if actor.principal_id:
        principal = ServicePrincipal.objects.get(pk=actor.principal_id)
        query = query.filter(batch__principal=principal, version__in=principal.versions.all(), device__in=principal.devices.all())
    elif role != Role.ADMIN:
        query = query.filter(batch__requester=user)
    if role != Role.ADMIN or actor.principal_id:
        if member is None:
            return query.none()
        query = query.filter(version__testgrant__membership=member, device__devicegrant__membership=member)
    return query.distinct()


def health(request):
    if request.method != "GET":
        return error("METHOD_NOT_ALLOWED", "Use GET.", 405)
    return JsonResponse({"status": "alive", "execution_available": False})


def ready(request):
    if request.method != "GET":
        return error("METHOD_NOT_ALLOWED", "Use GET.", 405)
    from django.db import connection
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        # Readiness requires migrations as well as a live database connection.
        from django.db.migrations.executor import MigrationExecutor
        pending = MigrationExecutor(connection).migration_plan(MigrationExecutor(connection).loader.graph.leaf_nodes())
        if pending:
            return JsonResponse({"status": "not_ready"}, status=503)
    except DatabaseError:
        return JsonResponse({"status": "not_ready"}, status=503)
    return JsonResponse({"status": "ready", "execution_available": False})


@api_view(["GET"])
def catalog(request, actor):
    project_id = identifier(request.GET.get("project_id"))
    user, project, role, member, principal = locked_scope(actor, project_id)
    devices, tests = records(user, project, role, member)
    if principal:
        devices = devices.filter(pk__in=principal.devices.values("pk"))
        tests = tests.filter(versions__in=principal.versions.all()).distinct()
    def permitted_versions(definition):
        query = definition.versions.order_by("number")
        if role != Role.ADMIN and not (role == Role.ENGINEER and definition.created_by_id == user.pk):
            query = query.filter(testgrant__membership=member)
        if principal:
            query = query.filter(pk__in=principal.versions.values("pk"))
        return query.distinct()[:50]
    return JsonResponse({"schema_version": 1, "devices": [{"id": str(d.pk), "name": d.name, "source": d.source,
                       "capabilities": d.capabilities, "online": False, "ready": False} for d in devices[:100]],
                       "tests": [{"id": str(t.pk), "name": t.name, "versions": [version_data(v) for v in permitted_versions(t)]} for t in tests[:100]],
                       "limit": 100, "execution_available": False})


@api_view(["POST", "GET"])
def jobs(request, actor):
    if request.method == "POST":
        batch, created = submit(actor, request.headers.get("Idempotency-Key"), body(request))
        return JsonResponse({"schema_version": 1, "batch_id": str(batch.pk), "jobs": [job_data(j) for j in batch.jobs.select_related("run").order_by("pk")]}, status=201 if created else 200)
    user, project, role, member, principal = locked_scope(actor, identifier(request.GET.get("project_id")))
    try:
        offset = int(request.GET.get("offset", 0))
        if not 0 <= offset <= 10000:
            raise ValueError
    except (TypeError, ValueError) as exc:
        raise ContractError("Invalid offset.") from exc
    query = visible_jobs(actor, user, project, role, member).order_by("-created_at", "pk")
    return JsonResponse({"schema_version": 1, "jobs": [job_data(j) for j in query[offset:offset + 50]], "limit": 50, "offset": offset})


@api_view(["GET"])
def job_detail(request, actor, job_id):
    job = Job.objects.select_related("batch").filter(pk=job_id).first()
    if job is None:
        raise Http404
    user, project, role, member, principal = locked_scope(actor, job.batch.project_id)
    permitted = visible_jobs(actor, user, project, role, member).filter(pk=job_id).first()
    if permitted is None:
        raise Http404
    return JsonResponse(job_data(permitted))


@api_view(["POST"])
def drafts(request, actor, project_id):
    definition = edit_draft(actor, project_id, body(request))
    return JsonResponse({"id": str(definition.pk)}, status=201)


@api_view(["POST"])
def draft_detail(request, actor, project_id, definition_id):
    definition = edit_draft(actor, project_id, body(request), definition_id)
    return JsonResponse({"id": str(definition.pk)})


@api_view(["POST"])
def publish_version(request, actor, project_id, definition_id):
    exact_keys(body(request), set())
    version = publish(actor, project_id, definition_id)
    return JsonResponse(version_data(version), status=201)


@api_view(["POST"])
def approve_version(request, actor, project_id, version_id):
    data = body(request)
    exact_keys(data, {"approved"})
    approval(actor, project_id, version_id, boolean(data["approved"]))
    return JsonResponse({"status": "updated"})


@api_view(["POST"])
def grant_version(request, actor, project_id, member_id):
    data = body(request)
    exact_keys(data, {"version_id", "granted"})
    version_grant(actor, project_id, member_id, identifier(data["version_id"]), boolean(data["granted"]))
    return JsonResponse({"status": "updated"})


@api_view(["POST"])
def inputs(request, actor, project_id):
    if request.content_type != "application/octet-stream" or int(request.headers.get("Content-Length", 0)) > 1024 * 1024:
        raise Rejected("INPUT_SIZE_LIMIT", "Use bounded application/octet-stream input.", 413)
    data = request.read(1024 * 1024 + 1)
    artifact, created = upload(actor, project_id, request.headers.get("X-Input-Name"), request.headers.get("X-Content-SHA256"), data)
    return JsonResponse({"id": str(artifact.pk), "sha256": artifact.sha256, "size": artifact.size}, status=201 if created else 200)


@api_view(["GET"])
def input_detail(request, actor, artifact_id):
    artifact = Artifact.objects.filter(pk=artifact_id).first()
    if artifact is None:
        raise Http404
    user, project, role, member, principal = locked_scope(actor, artifact.project_id)
    if not artifact_visible(actor, artifact, user, role):
        raise Http404
    response = HttpResponse(read_input(artifact), content_type="application/octet-stream")
    response["Content-Disposition"] = f'attachment; filename="{artifact.name}"'
    return response


@api_view(["POST"])
def principals(request, actor, project_id):
    user, project, *_ = locked_scope(actor, project_id, manager=True)
    data = body(request)
    exact_keys(data, {"owner_id", "name", "version_ids", "device_ids"})
    if type(data["owner_id"]) is not int or not isinstance(data["name"], str) or not 1 <= len(data["name"].strip()) <= 80:
        raise ContractError("Invalid owner/name.")
    owner = Membership.objects.filter(project=project, user_id=data["owner_id"], active=True, user__is_active=True).exclude(role=Role.VIEWER).first()
    if owner is None:
        raise Http404
    for name in ["version_ids", "device_ids"]:
        if not isinstance(data[name], list) or not 1 <= len(data[name]) <= 20:
            raise ContractError("Provide 1-20 explicit scopes.")
    versions = list(TestVersion.objects.filter(pk__in=[identifier(v) for v in data["version_ids"]], definition__project=project))
    devices = list(Device.objects.filter(pk__in=[identifier(d) for d in data["device_ids"]], project=project))
    if len(versions) != len(set(data["version_ids"])) or len(devices) != len(set(data["device_ids"])):
        raise Http404
    principal = ServicePrincipal.objects.create(project=project, owner=owner.user, name=data["name"].strip())
    principal.versions.set(versions)
    principal.devices.set(devices)
    audit(user, project, "service_principal.created", principal.pk)
    return JsonResponse({"id": str(principal.pk)}, status=201)


@api_view(["POST"])
def tokens(request, actor, project_id, principal_id):
    data = body(request)
    exact_keys(data, {"action"})
    user, project, *_ = locked_scope(actor, project_id, manager=True)
    principal = ServicePrincipal.objects.filter(pk=principal_id, project=project).first()
    if principal is None:
        raise Http404
    if data["action"] == "rotate":
        secret, token = rotate_token(actor, project_id, principal.pk)
        return JsonResponse({"token": secret, "token_id": str(token.pk), "expires_at": token.expires_at.isoformat()})
    if data["action"] == "revoke":
        ServiceToken.objects.filter(principal=principal, revoked_at=None).update(revoked_at=timezone.now())
    elif data["action"] == "deactivate":
        principal.active = False
        principal.save(update_fields=["active"])
        ServiceToken.objects.filter(principal=principal, revoked_at=None).update(revoked_at=timezone.now())
    else:
        raise ContractError("Unsupported action.")
    audit(user, project, "service_token.revoked", principal.pk)
    return JsonResponse({"status": "updated"})


@api_view(["POST"])
def account(request, actor, user_id):
    data = body(request)
    exact_keys(data, {"action"})
    account_access(actor, user_id, data["action"])
    return JsonResponse({"status": "updated"})


@api_view(["POST"])
def invitation_revoke(request, actor, project_id, invitation_id):
    exact_keys(body(request), set())
    revoke_invitation(actor, project_id, invitation_id)
    return JsonResponse({"status": "updated"})
