"""Dedicated agent authority. No browser/CI fallback and no dispatch endpoint."""
from functools import wraps
from django.core.exceptions import RequestDataTooBig, ValidationError
from django.db import DatabaseError, transaction
from django.http import Http404, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from contracts.v1 import ContractError, exact_keys
from .api import api_view, body, error
from .agent_services import create_agent, enroll, heartbeat, manage_agent
from .models import Agent
from .submissions import Rejected, locked_scope


@api_view(["GET", "POST"])
def administrators(request, actor, project_id):
    user, project, *_ = locked_scope(actor, project_id, manager=True)
    if request.method == "POST":
        payload = body(request)
        exact_keys(payload, {"name", "device_ids"})
        agent, invitation = create_agent(actor, project.pk, payload["name"], payload["device_ids"])
        return JsonResponse(invitation, status=201)
    records = Agent.objects.filter(project=project).order_by("created_at", "pk")[:100]
    return JsonResponse({"schema_version": 1, "agents": [
        {"id": str(agent.pk), "name": agent.name, "enabled": agent.enabled, "enrolled": agent.enrolled_at is not None,
         "last_contact_at": agent.last_contact_at.isoformat() if agent.last_contact_at else None,
         "reported_platform": agent.reported_platform or None, "reported_version": agent.reported_version or None,
         "device_ids": [str(link.device_id) for link in agent.agentdevice_set.filter(active=True)],
         "devices_ready": False, "execution_available": False} for agent in records], "limit": 100})


@api_view(["POST"])
def administrator_detail(request, actor, project_id, agent_id):
    payload = body(request)
    exact_keys(payload, {"action"}, {"device_ids"})
    if payload["action"] != "set_devices" and "device_ids" in payload:
        raise ContractError("Unexpected scope field.")
    return JsonResponse(manage_agent(actor, project_id, agent_id, payload["action"], payload.get("device_ids")))


def agent_endpoint(scheme, function, *, binary=False):
    @csrf_exempt
    @wraps(function)
    def endpoint(request, agent_id):
        try:
            authorization = request.headers.get("Authorization", "")
            if not authorization.startswith(scheme + " ") or len(authorization) > 200:
                raise Rejected("UNAUTHENTICATED", "An explicit agent credential is required.", 401)
            if request.method != "POST":
                response = error("METHOD_NOT_ALLOWED", "Use POST.", 405)
                response["Allow"] = "POST"
                return response
            # Authentication and mutation commit/rollback together; endpoints never accept cookies.
            with transaction.atomic():
                payload = request if binary else body(request)
                response = function(agent_id, authorization[len(scheme) + 1:], payload)
                return response if isinstance(response,HttpResponse) else JsonResponse(response)
        except Rejected as exc:
            return error(exc.code, exc.message, exc.status)
        except (ContractError, ValidationError, ValueError, TypeError):
            return error("INVALID_INPUT", "Invalid or unsupported agent protocol message.", 400)
        except RequestDataTooBig:
            return error("INPUT_SIZE_LIMIT", "Agent message size limit exceeded.", 413)
        except Http404:
            return error("NOT_FOUND", "Agent unavailable.", 404)
        except DatabaseError:
            return error("DEPENDENCY_UNAVAILABLE", "Agent contact is temporarily unavailable.", 503)
    return endpoint


enrollment = agent_endpoint("Enrollment", enroll)
contact = agent_endpoint("Bearer", heartbeat)
