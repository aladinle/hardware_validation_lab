from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from lab.models import Membership, Project, Role
from lab.services import audit


class Command(BaseCommand):
    help = "Trusted local administrator operation: add an existing account to a project."

    def add_arguments(self, parser):
        parser.add_argument("email")
        parser.add_argument("project_id")
        parser.add_argument("role", choices=Role.values)

    @transaction.atomic
    def handle(self, email, project_id, role, **options):
        try:
            user = get_user_model().objects.get(email=email.lower(), is_active=True)
            project = Project.objects.get(pk=project_id)
        except (get_user_model().DoesNotExist, Project.DoesNotExist, ValueError) as exc:
            raise CommandError("Active account or project not found.") from exc
        membership, _ = Membership.objects.update_or_create(user=user, project=project, defaults={"role": role, "active": True})
        audit(None, project, "membership.local_command", f"{membership.pk}:{role}")
        self.stdout.write("Membership updated. Local OS operator attribution is recorded as a command, not a human web session.")
