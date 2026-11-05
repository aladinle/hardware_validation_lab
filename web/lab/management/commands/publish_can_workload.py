"""Publish a new package-bound version; approval/grants remain separate."""
from django.core.management.base import BaseCommand, CommandError
from django.http import Http404
from contracts.v1 import ContractError
from lab.models import User
from lab.submissions import Actor, Rejected, publish


class Command(BaseCommand):
    help = "Publish a new synthetic CAN comparator version from an installed matching wheel; no approval or execution."

    def add_arguments(self, parser):
        parser.add_argument("project_id")
        parser.add_argument("definition_id")
        parser.add_argument("author_email")
        parser.add_argument("--wheel", required=True)

    def handle(self, project_id, definition_id, author_email, **options):
        try:
            user = User.objects.get(email=author_email.lower(), is_active=True)
            version = publish(Actor(user.pk), project_id, definition_id, workload_wheel=options["wheel"])
        except (User.DoesNotExist, ContractError, Rejected, Http404, ValueError, OSError) as exc:
            raise CommandError("Publication denied or local wheel unavailable; verify author, draft and matching installed package.") from exc
        self.stdout.write(f"Created immutable version {version.pk} (number {version.number}). "
                          f"Wheel SHA-256: {version.manifest['plugin_package_sha256']}. "
                          "Separate administrator approval and explicit version grants required; dispatch remains disabled.")
