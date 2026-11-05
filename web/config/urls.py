from django.urls import path
from django.views.generic import TemplateView
from lab import views
from lab import api
from lab import portal_jobs
from lab import agent_api
from lab import agent_portal

urlpatterns = [
    path("api/v1/projects/<uuid:project_id>/agents", agent_api.administrators),
    path("api/v1/projects/<uuid:project_id>/agents/<uuid:agent_id>", agent_api.administrator_detail),
    path("api/v1/agents/<uuid:agent_id>/enroll", agent_api.enrollment),
    path("api/v1/agents/<uuid:agent_id>/heartbeat", agent_api.contact),
    path("health/", api.health),
    path("ready/", api.ready),
    path("api/v1/catalog", api.catalog),
    path("api/v1/devices", api.catalog),
    path("api/v1/tests", api.catalog),
    path("api/v1/jobs", api.jobs),
    path("api/v1/jobs/<uuid:job_id>", api.job_detail),
    path("api/v1/projects/<uuid:project_id>/drafts", api.drafts),
    path("api/v1/projects/<uuid:project_id>/drafts/<uuid:definition_id>", api.draft_detail),
    path("api/v1/projects/<uuid:project_id>/drafts/<uuid:definition_id>/publish", api.publish_version),
    path("api/v1/projects/<uuid:project_id>/versions/<uuid:version_id>/approval", api.approve_version),
    path("api/v1/projects/<uuid:project_id>/members/<int:member_id>/versions", api.grant_version),
    path("api/v1/projects/<uuid:project_id>/inputs", api.inputs),
    path("api/v1/inputs/<uuid:artifact_id>", api.input_detail),
    path("api/v1/projects/<uuid:project_id>/principals", api.principals),
    path("api/v1/projects/<uuid:project_id>/principals/<uuid:principal_id>/tokens", api.tokens),
    path("api/v1/accounts/<int:user_id>", api.account),
    path("api/v1/projects/<uuid:project_id>/invitations/<int:invitation_id>/revoke", api.invitation_revoke),
    path("", views.home, name="home"),
    path("login/", views.LabLoginView.as_view(), name="login"),
    path("logout/", views.LabLogoutView.as_view(), name="logout"),
    path("accept/", views.accept, name="accept"),
    path("recovery/", views.RecoveryView.as_view(), name="password_reset"),
    path("recovery/sent/", TemplateView.as_view(template_name="recovery_sent.html")),
    path("recovery/<uidb64>/<token>/", views.RecoveryConfirmView.as_view(), name="password_reset_confirm"),
    path("projects/<uuid:project_id>/", views.project, name="project"),
    path("projects/<uuid:project_id>/agents/", agent_portal.agents, name="agents"),
    path("projects/<uuid:project_id>/queue/", portal_jobs.queue, name="queue"),
    path("projects/<uuid:project_id>/inputs/", portal_jobs.input_upload, name="input_upload"),
    path("projects/<uuid:project_id>/workbench/", portal_jobs.workbench, name="workbench"),
    path("projects/<uuid:project_id>/jobs/<uuid:job_id>/", portal_jobs.job_page, name="job_page"),
    path("projects/<uuid:project_id>/view/<str:section>/", views.project, name="section"),
    path("projects/<uuid:project_id>/records/<str:kind>/<uuid:record_id>/", views.detail, name="detail"),
    path("projects/<uuid:project_id>/invite/", views.create_invite, name="create_invite"),
    path("projects/<uuid:project_id>/members/<int:member_id>/", views.change_member, name="change_member"),
    path("projects/<uuid:project_id>/members/<int:member_id>/grants/", views.change_grant, name="change_grant"),
    path("projects/<uuid:project_id>/runs/", views.submit_run, name="submit_run"),
]
