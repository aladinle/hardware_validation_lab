"""Create isolated disposable browser-review data. Never touches the user's lab DB."""
import json
import os
import secrets
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root / "web"))
expected = root / ".local" / "browser-review.sqlite3"
if os.environ.get("LAB_DB") != "sqlite" or Path(os.environ.get("LAB_SQLITE_PATH", "")).resolve() != expected.resolve():
    raise SystemExit("Requires LAB_DB=sqlite and LAB_SQLITE_PATH=.local/browser-review.sqlite3 (absolute).")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django
django.setup()
from django.core.management import call_command
from lab.models import Membership, Project, Role, User

call_command("migrate", verbosity=0)
if User.objects.exists():
    raise SystemExit("Review database already populated; preserving it.")
password = secrets.token_urlsafe(30)
user = User.objects.create_superuser(username="review@localhost.test", email="review@localhost.test", password=password)
project = Project.objects.create(name="Portal review (temporary)")
Membership.objects.create(user=user, project=project, role=Role.ADMIN)
(root / ".local" / "browser-review.json").write_text(json.dumps({"email": user.email, "password": password}), encoding="utf-8")
print("Isolated review database prepared; no device records, runs, or results. Credentials are private and temporary.")
