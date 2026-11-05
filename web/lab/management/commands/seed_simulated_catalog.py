"""Opt-in metadata only. No synthetic run/result or connected hardware is created."""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from lab.models import Device, DeviceGrant, Membership, Role, TestDefinition, TestGrant, User
from lab.services import audit
from lab.submissions import Actor, approval, publish


class Command(BaseCommand):
    help = "Seed approved synthetic CAN catalog metadata and grants in an existing project (no execution)."

    def add_arguments(self, parser):
        parser.add_argument("project_id")
        parser.add_argument("administrator_email")
        parser.add_argument("--confirm-simulated", action="store_true", required=True)

    @transaction.atomic
    def handle(self, project_id, administrator_email, **options):
        try:
            user = User.objects.get(email=administrator_email.lower(), is_active=True)
            member = Membership.objects.get(user=user, project_id=project_id, active=True, role=Role.ADMIN)
        except (User.DoesNotExist, Membership.DoesNotExist, ValueError) as exc:
            raise CommandError("An active project administrator membership is required.") from exc
        device, _ = Device.objects.get_or_create(project=member.project, name="Simulated CAN file station (offline)", defaults={"source": "simulated", "capabilities": ["can_payload_files"]})
        if device.source != "simulated" or device.capabilities != ["can_payload_files"]:
            raise CommandError("Existing inventory conflicts with the explicit simulator metadata; preserving it.")
        definition, _ = TestDefinition.objects.get_or_create(project=member.project, name="Synthetic CAN file comparison", defaults={"created_by": user, "draft_header_bytes": 0})
        version = definition.versions.order_by("number").first()
        if version is None:
            version = publish(Actor(user.pk), member.project_id, definition.pk)
        approval(Actor(user.pk), member.project_id, version.pk, True)
        TestGrant.objects.get_or_create(membership=member, test=definition, version=version)
        DeviceGrant.objects.get_or_create(membership=member, device=device)
        audit(user, member.project, "catalog.simulated_seed", device.pk)
        self.stdout.write(f"Simulated metadata only; offline, no execution. Device {device.pk}; version {version.pk}.")
