from django.http import Http404
from django.db.models import Q
from .models import Device, Membership, Project, Role, TestDefinition


def projects_for(user):
    if not user.is_active:
        return Project.objects.none()
    if user.is_superuser:
        return Project.objects.all().order_by("name")
    return Project.objects.filter(membership__user=user, membership__active=True).order_by("name")


def scope(user, project_id):
    try:
        project = projects_for(user).get(pk=project_id)
    except Project.DoesNotExist:
        raise Http404
    if user.is_superuser:
        return project, Role.ADMIN, None
    member = Membership.objects.get(project=project, user=user, active=True)
    return project, member.role, member


def records(user, project, role, member):
    devices = Device.objects.filter(project=project)
    tests = TestDefinition.objects.filter(project=project)
    if role != Role.ADMIN:
        devices = devices.filter(devicegrant__membership=member)
        tests = tests.filter(Q(testgrant__membership=member) | (Q(created_by=user) if role == Role.ENGINEER else Q(pk__in=[])))
    return devices.order_by("name").distinct(), tests.order_by("name").distinct()
