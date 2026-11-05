from getpass import getpass
from django.contrib.auth import get_user_model, password_validation
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from lab.models import Membership, Project, Role
from lab.services import audit


class Command(BaseCommand):
    help = "Interactively create the first local platform administrator and project. No shared credentials."

    @transaction.atomic
    def handle(self, *args, **options):
        User = get_user_model()
        if User.objects.filter(is_superuser=True).exists():
            raise CommandError("Bootstrap already completed. Use existing administrator credentials.")
        email = input("Administrator email: ").strip().lower()
        name = input("Project name: ").strip()
        password = getpass("Password (12+ characters): ")
        confirm = getpass("Confirm password: ")
        try:
            validate_email(email)
            password_validation.validate_password(password, User(username=email, email=email))
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages)) from exc
        if password != confirm or not name:
            raise CommandError("Passwords must match and a project name is required.")
        user = User.objects.create_superuser(username=email, email=email, password=password)
        project = Project.objects.create(name=name)
        Membership.objects.create(project=project, user=user, role=Role.ADMIN)
        audit(user, project, "bootstrap.created", user.pk)
        self.stdout.write(self.style.SUCCESS("Local administrator and project created."))
