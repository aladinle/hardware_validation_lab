from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView, PasswordResetConfirmView, PasswordResetView
from django.db import IntegrityError, transaction
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_POST
from .access import projects_for, records, scope
from .forms import AcceptForm, GrantForm, InviteForm, LoginForm, MemberForm
from .models import AuditEvent, Device, DeviceGrant, Invitation, Membership, Role, TestDefinition, TestGrant
from .services import accept_invite, audit, digest, invite, throttled


class LabLoginView(LoginView):
    template_name = "login.html"
    authentication_form = LoginForm

    @method_decorator(sensitive_post_parameters("password"))
    def post(self, request, *args, **kwargs):
        if throttled(request, request.POST.get("username", "")):
            form = self.get_form()
            # Do not authenticate blocked requests.
            from django import forms
            form._errors = forms.utils.ErrorDict()
            form.cleaned_data = {}
            form.add_error(None, "Unable to sign in with those credentials. Try again later.")
            return self.render_to_response(self.get_context_data(form=form), status=429)
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        response = super().form_valid(form)
        audit(self.request.user, None, "session.login")
        return response


class LabLogoutView(LogoutView):
    next_page = "login"

    def post(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            audit(request.user, None, "session.logout")
        return super().post(request, *args, **kwargs)


class RecoveryConfirmView(PasswordResetConfirmView):
    template_name = "recovery_confirm.html"
    success_url = "/login/"

    @transaction.atomic
    def form_valid(self, form):
        response = super().form_valid(form)
        audit(self.user, None, "account.password_recovered", self.user.pk)
        return response


class RecoveryView(PasswordResetView):
    template_name = "recovery.html"
    email_template_name = "recovery_email.txt"
    subject_template_name = "recovery_subject.txt"
    success_url = "/recovery/sent/"

    def post(self, request, *args, **kwargs):
        if throttled(request, request.POST.get("email", ""), "recovery"):
            return redirect(self.success_url)
        return super().post(request, *args, **kwargs)


@sensitive_post_parameters("password", "confirm_password", "token")
def accept(request):
    # Token travels in a form body after entry, never in the URL/access log.
    token = request.POST.get("token", "")
    invitation = Invitation.objects.filter(token_hash=digest(token), consumed_at=None, revoked_at=None, expires_at__gt=timezone.now()).first()
    form = AcceptForm(request.POST or None, email=invitation.email if invitation else "")
    if request.method == "POST":
        if throttled(request, "invitation", "invite"):
            return HttpResponse("Too many attempts. Try again later.", status=429)
        if invitation and form.is_valid():
            try:
                accept_invite(token, form.cleaned_data["password"])
            except (ValueError, IntegrityError, Invitation.DoesNotExist):
                form.add_error(None, "Invitation unavailable. Ask your administrator for a new invitation.")
            else:
                messages.success(request, "Account created. Sign in with your email and password.")
                return redirect("login")
        elif not invitation:
            form.add_error(None, "Invitation unavailable. Ask your administrator for a new invitation.")
    return render(request, "accept.html", {"form": form, "token": token})


@login_required
def home(request):
    projects = projects_for(request.user)
    if projects.exists():
        return redirect("project", project_id=projects.first().pk)
    return render(request, "no_projects.html")


def context(request, project_id, section="Overview"):
    project, role, member = scope(request.user, project_id)
    devices, tests = records(request.user, project, role, member)
    return {"project": project, "role": role, "role_label": Role(role).label,
            "is_manager": role == Role.ADMIN, "projects": projects_for(request.user),
            "devices": devices, "tests": tests, "section": section,
            "nav": [("overview", "Overview"), ("devices", "Devices"), ("catalog", "Test Catalog"),
                    ("runs", "Test Runs"), ("results", "Results")] + ([("users", "Users & Roles"), ("audit", "Audit Log")] if role == Role.ADMIN else [])}


@login_required
def project(request, project_id, section="overview"):
    labels = {"overview": "Overview", "devices": "Devices", "catalog": "Test Catalog", "runs": "Test Runs", "results": "Results", "users": "Users & Roles", "audit": "Audit Log"}
    if section not in labels:
        raise Http404
    ctx = context(request, project_id, labels[section])
    if section in {"users", "audit"} and not ctx["is_manager"]:
        raise Http404
    if request.method != "GET":
        return HttpResponse("Method not allowed", status=405)
    ctx.update({"page": section, "invite_form": InviteForm(), "roles": Role.choices})
    if section == "catalog":
        from .models import TestVersion
        member = Membership.objects.filter(user=request.user, project=ctx["project"], active=True).first()
        ctx["catalog_entries"] = []
        for definition in ctx["tests"]:
            versions = TestVersion.objects.filter(definition=definition)
            if ctx["role"] != Role.ADMIN and not (ctx["role"] == Role.ENGINEER and definition.created_by_id == request.user.pk):
                versions = versions.filter(testgrant__membership=member)
            ctx["catalog_entries"].append({"test": definition, "versions": versions.distinct().order_by("number")})
    if section == "runs":
        from .api import visible_jobs
        from .submissions import Actor
        member = Membership.objects.filter(user=request.user, project=ctx["project"], active=True).first()
        ctx["jobs"] = visible_jobs(Actor(request.user.pk), request.user, ctx["project"], ctx["role"], member).order_by("-created_at")[:50]
    if ctx["is_manager"]:
        ctx["members"] = Membership.objects.filter(project=ctx["project"]).select_related("user")
        from django.db.models import Q
        event_filter = Q(project=ctx["project"])
        if request.user.is_superuser:
            event_filter |= Q(project=None)
        ctx["events"] = AuditEvent.objects.filter(event_filter).select_related("actor").order_by("-created_at")[:100]
        ctx["device_grants"] = DeviceGrant.objects.filter(membership__project=ctx["project"]).select_related("membership__user", "device")
        ctx["test_grants"] = TestGrant.objects.filter(membership__project=ctx["project"]).select_related("membership__user", "test")
    return render(request, "portal.html", ctx)


@login_required
def detail(request, project_id, kind, record_id):
    ctx = context(request, project_id, "Record details")
    queryset = ctx["devices"] if kind == "device" else ctx["tests"] if kind == "test" else None
    if queryset is None:
        raise Http404
    ctx["record"] = get_object_or_404(queryset, pk=record_id)
    return render(request, "detail.html", ctx)


@login_required
@require_POST
def create_invite(request, project_id):
    ctx = context(request, project_id, "Users & Roles")
    if not ctx["is_manager"]:
        raise Http404
    form = InviteForm(request.POST)
    if form.is_valid():
        token = invite(request.user, ctx["project"], **form.cleaned_data)
        response = render(request, "invitation_created.html", {**ctx, "token": token})
        response["Cache-Control"] = "no-store"
        return response
    return render(request, "form.html", {**ctx, "form": form}, status=400)


@login_required
@require_POST
@transaction.atomic
def change_member(request, project_id, member_id):
    from .submissions import Actor, Rejected, locked_scope
    ctx = context(request, project_id, "Users & Roles")
    if not ctx["is_manager"]:
        raise Http404
    try:
        locked_scope(Actor(request.user.pk), project_id, manager=True)
    except Rejected as exc:
        raise Http404 from exc
    member = get_object_or_404(Membership.objects.select_for_update(), pk=member_id, project=ctx["project"])
    form = MemberForm(request.POST)
    if not form.is_valid():
        return render(request, "form.html", {**ctx, "form": form}, status=400)
    if member.user_id == request.user.pk:
        return HttpResponse("Ask another administrator to change your own membership.", status=400)
    member.role = form.cleaned_data["role"]
    member.active = form.cleaned_data["active"]
    member.save(update_fields=["role", "active"])
    audit(request.user, ctx["project"], "membership.changed", f"{member.pk}:{member.role}:{member.active}")
    return redirect("section", project_id=project_id, section="users")


@login_required
@require_POST
@transaction.atomic
def change_grant(request, project_id, member_id):
    from .submissions import Actor, Rejected, locked_scope
    ctx = context(request, project_id, "Users & Roles")
    if not ctx["is_manager"]:
        raise Http404
    try:
        locked_scope(Actor(request.user.pk), project_id, manager=True)
    except Rejected as exc:
        raise Http404 from exc
    member = get_object_or_404(Membership, pk=member_id, project=ctx["project"])
    form = GrantForm(request.POST)
    if not form.is_valid():
        return HttpResponse("Invalid grant", status=400)
    data = form.cleaned_data
    model, grants, field = (Device, DeviceGrant, "device") if data["kind"] == "device" else (TestDefinition, TestGrant, "test")
    record = get_object_or_404(model, pk=data["record"], project=ctx["project"])
    lookup = {"membership": member, field: record}
    if field == "test":
        lookup["version"] = None
    if data["granted"]:
        grants.objects.get_or_create(**lookup)
    else:
        grants.objects.filter(**lookup).delete()
    audit(request.user, ctx["project"], "grant.changed", f"{member.pk}:{field}:{record.pk}:{data['granted']}")
    return redirect("section", project_id=project_id, section="users")


@login_required
@require_POST
def submit_run(request, project_id):
    ctx = context(request, project_id)
    if ctx["role"] == Role.VIEWER:
        return HttpResponse("You do not have permission to submit runs.", status=403)
    return HttpResponse("Execution is not available in this milestone.", status=409)
