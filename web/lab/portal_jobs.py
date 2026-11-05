import uuid
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.db import transaction
from django.utils import timezone
from contracts.v1 import ContractError
from .api import visible_jobs
from .forms import DraftForm, InputForm, QueueForm
from .models import Membership, Role, TestDefinition
from .submissions import Actor, Rejected, approval, edit_draft, locked_scope, publish, submit, upload, version_grant
from .views import context


@login_required
def queue(request, project_id):
    ctx = context(request, project_id, "Test Runs")
    if ctx["role"] == Role.VIEWER:
        return HttpResponse("Read-only access: you cannot submit runs.", status=403)
    form = QueueForm(request.POST if request.method == "POST" else None, user=request.user, project=ctx["project"], initial={"idempotency_key": str(uuid.uuid4())})
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        payload = {"project_id": str(project_id), "queue_seconds": data["queue_seconds"], "items": [{"version_id": str(data["version"].pk), "device_id": str(data["device"].pk),
                   "expected_artifact_id": str(data["expected"].pk), "actual_artifact_id": str(data["actual"].pk), "parameters": {"header_bytes": data["header_bytes"]}}]}
        try:
            batch, created = submit(Actor(request.user.pk), data["idempotency_key"], payload)
        except (Rejected, ContractError) as exc:
            form.add_error(None, exc.message if isinstance(exc, Rejected) else str(exc))
        else:
            return redirect("job_page", project_id=project_id, job_id=batch.jobs.first().pk)
    return render(request, "queue.html", {**ctx, "form": form})


@login_required
@transaction.atomic
def job_page(request, project_id, job_id):
    ctx = context(request, project_id, "Test Runs")
    user, project, role, member, principal = locked_scope(Actor(request.user.pk), project_id)
    job = visible_jobs(Actor(user.pk), user, project, role, member).filter(pk=job_id).first()
    if job is None:
        raise Http404
    return render(request, "job.html", {**ctx, "job": job, "now": timezone.now()})


@login_required
def input_upload(request, project_id):
    ctx = context(request, project_id, "Test Runs")
    if ctx["role"] == Role.VIEWER:
        return HttpResponse("Read-only access.", status=403)
    form = InputForm(request.POST if request.method == "POST" else None, request.FILES or None)
    artifact = None
    if request.method == "POST" and form.is_valid():
        file = form.cleaned_data["file"]
        try:
            artifact, created = upload(Actor(request.user.pk), project_id, file.name, form.cleaned_data["sha256"], file.read(1024 * 1024 + 1))
        except (Rejected, ContractError) as exc:
            form.add_error(None, exc.message if isinstance(exc, Rejected) else str(exc))
    return render(request, "input_upload.html", {**ctx, "form": form, "artifact": artifact})


@login_required
def workbench(request, project_id):
    ctx = context(request, project_id, "Test Catalog")
    if ctx["role"] not in {Role.ADMIN, Role.ENGINEER}:
        raise Http404
    form = DraftForm(request.POST if request.method == "POST" else None)
    notice = ""
    if request.method == "POST":
        try:
            action = request.POST.get("action")
            if action == "save" and form.is_valid():
                definition = edit_draft(Actor(request.user.pk), project_id, {"name": form.cleaned_data["name"], "header_bytes": form.cleaned_data["header_bytes"]}, form.cleaned_data["definition_id"])
                notice = f"Draft saved: {definition.pk}"
            elif action == "publish":
                version = publish(Actor(request.user.pk), project_id, uuid.UUID(request.POST.get("definition_id", "")))
                notice = f"Immutable version {version.number} published; administrator approval is required."
            elif action in {"approve", "revoke"}:
                approval(Actor(request.user.pk), project_id, uuid.UUID(request.POST.get("version_id", "")), action == "approve")
                notice = "Approval updated."
            elif action in {"grant", "ungrant"}:
                version_grant(Actor(request.user.pk), project_id, int(request.POST.get("member_id", "")), uuid.UUID(request.POST.get("version_id", "")), action == "grant")
                notice = "Version grant updated. Device access must be granted separately in Users & Roles."
            elif action != "save":
                raise ContractError("Unsupported action.")
        except (Rejected, ContractError, ValueError) as exc:
            notice = exc.message if isinstance(exc, Rejected) else "Invalid action or identifier."
    drafts = TestDefinition.objects.filter(project=ctx["project"]).prefetch_related("versions__approvals")
    if ctx["role"] == Role.ENGINEER:
        drafts = drafts.filter(created_by=request.user)
    return render(request, "workbench.html", {**ctx, "form": form, "drafts": drafts, "notice": notice,
                   "members": Membership.objects.filter(project=ctx["project"], active=True).select_related("user") if ctx["is_manager"] else []})
