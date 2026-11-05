"""Project-admin enrollment downloads; credentials are never placed in URLs or logs."""
import json
from django import forms
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import render
from contracts.v1 import ContractError
from .agent_services import create_agent, manage_agent
from .models import Agent, Device
from .submissions import Actor, Rejected
from .views import context


class AgentForm(forms.Form):
    name = forms.CharField(max_length=80, label="Agent name")
    devices = forms.ModelMultipleChoiceField(queryset=Device.objects.none(), label="Approved inventory scope")

    def __init__(self, *args, project, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["devices"].queryset = Device.objects.filter(project=project, enabled=True).order_by("name")


@login_required
def agents(request, project_id):
    if request.method not in {"GET", "POST"}:
        return HttpResponse("Use GET or POST.", status=405)
    ctx = context(request, project_id, "Devices")
    if not ctx["is_manager"]:
        raise Http404
    form = AgentForm(request.POST if request.method == "POST" and request.POST.get("action") == "create" else None, project=ctx["project"])
    notice = ""
    if request.method == "POST":
        try:
            action = request.POST.get("action")
            if action == "create":
                if form.is_valid():
                    agent, document = create_agent(Actor(request.user.pk), project_id, form.cleaned_data["name"], [str(device.pk) for device in form.cleaned_data["devices"]])
                else:
                    document = None
            else:
                from uuid import UUID
                if action not in {"rotate", "reenroll", "revoke", "disable"}:
                    raise ContractError("Unsupported action.")
                document = manage_agent(Actor(request.user.pk), project_id, UUID(request.POST.get("agent_id", "")), action)
            if document and "token" in document:
                response = HttpResponse(json.dumps(document), content_type="application/json")
                response["Content-Disposition"] = 'attachment; filename="agent-credential.json"'
                response["Cache-Control"] = "no-store, private"
                return response
            if document:
                notice = "Agent credential access updated. No device readiness or execution was changed."
        except (Rejected, ContractError, ValueError) as exc:
            notice = exc.message if isinstance(exc, Rejected) else "Invalid agent request."
    return render(request, "agents.html", {**ctx, "form": form, "notice": notice,
                   "agents": Agent.objects.filter(project=ctx["project"]).order_by("created_at")[:100]})
