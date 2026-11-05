"""Isolated identity/contact review lifecycle; no real human credentials or hardware."""
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sys

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root / "web"))
if os.environ.get("LAB_DB") != "postgres" or os.environ.get("PGDATABASE") != "hardware_lab_b1_review":
    raise SystemExit("Use only the isolated hardware_lab_b1_review PostgreSQL database.")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django
django.setup()
from django.core.management import call_command
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from lab.models import Agent, AgentCredential, AgentEnrollment, Device, Job, Membership, Project, Role, User

private = root / ".local" / "b1-review.json"
mode = sys.argv[1]
if mode == "prepare":
    call_command("migrate", verbosity=0)
    if User.objects.exists():
        raise SystemExit("Review database already populated; preserving it.")
    password = secrets.token_urlsafe(30)
    user = User.objects.create_user(username="b1-review@localhost.test", email="b1-review@localhost.test", password=password)
    project = Project.objects.create(name="M2B.1 identity review (temporary)")
    Membership.objects.create(user=user, project=project, role=Role.ADMIN)
    device = Device.objects.create(project=project, name="Synthetic inventory scope (no discovery)", source="simulated")
    private.write_text(json.dumps({"email": user.email, "password": password, "project_id": str(project.pk), "device_id": str(device.pk)}), encoding="utf-8")
    print("Prepared isolated administrator and offline synthetic inventory. No agent, job or execution seeded.")
elif mode == "render":
    review = json.loads(private.read_text(encoding="utf-8"))
    user = User.objects.get(email=review["email"])
    client = Client(HTTP_HOST="127.0.0.1")
    client.force_login(user)
    response = client.get(reverse("agents", args=[review["project_id"]]))
    assert response.status_code == 200
    assert Job.objects.count() == 0
    html = response.content.decode()
    html = html.replace('<main id="main" class="content">', '<main id="main" class="content"><div class="notice">Layout snapshot only · isolated contact test data · forms inactive · no hardware discovered</div>')
    html = re.sub(r'<input type="hidden" name="csrfmiddlewaretoken"[^>]*>', '', html)
    html = re.sub(r'<form\b[^>]*>', '<div class="snapshot-form">', html).replace('</form>', '</div>')
    html = html.replace('<button ', '<button disabled ')
    output = root / ".local" / "b1-preview"
    (output / "static").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(root / "web/static/lab.css", output / "static/lab.css")
    (output / "agents.html").write_text(html, encoding="utf-8")
    print("Exported labeled agent-admin layout snapshot; all forms inactive and no credential values included.")
elif mode == "retire":
    review = json.loads(private.read_text(encoding="utf-8"))
    user = User.objects.get(email=review["email"])
    user.is_active = False
    user.session_epoch += 1
    user.set_unusable_password()
    user.save(update_fields=["is_active", "session_epoch", "password"])
    Agent.objects.all().update(enabled=False)
    AgentCredential.objects.filter(revoked_at=None).update(revoked_at=timezone.now())
    AgentEnrollment.objects.filter(revoked_at=None).update(revoked_at=timezone.now())
    private.unlink()
    for name in ["b1-enrollment.json", "b1-state.json", "b1-rotated.json", "b1-state-rotated.json", "b1-final-credential.json", "b1-state-final.json"]:
        (root / ".local" / name).unlink(missing_ok=True)
    print("Retired isolated review credentials; preserved records, no jobs/execution.")
else:
    raise SystemExit("Use prepare/render/retire.")
