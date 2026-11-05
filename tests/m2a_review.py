"""Isolated PostgreSQL review lifecycle. Not an application bootstrap or shared account."""
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sys

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root / "web"))
if os.environ.get("LAB_DB") != "postgres" or os.environ.get("PGDATABASE") != "hardware_lab_m2a_review":
    raise SystemExit("Use only the isolated hardware_lab_m2a_review PostgreSQL database.")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django
django.setup()
from django.core.management import call_command
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from lab.models import Device, Job, Project, ServicePrincipal, ServiceToken, TestVersion, User
from lab.submissions import Actor, ServicePrincipal, checksum, rotate_token, submit, upload

mode = sys.argv[1]
private = root / ".local" / "m2a-review.json"
if mode == "prepare":
    call_command("migrate", verbosity=0)
    if User.objects.exists():
        raise SystemExit("Review DB already populated; preserving it.")
    password = secrets.token_urlsafe(30)
    user = User.objects.create_superuser(username="m2a-review@localhost.test", email="m2a-review@localhost.test", password=password)
    project = Project.objects.create(name="M2A review (temporary, simulated)")
    from lab.models import Membership, Role
    Membership.objects.create(user=user, project=project, role=Role.ADMIN)
    call_command("seed_simulated_catalog", str(project.pk), user.email, confirm_simulated=True, verbosity=0)
    device = Device.objects.get(project=project)
    version = TestVersion.objects.get(definition__project=project)
    principal = ServicePrincipal.objects.create(owner=user, project=project, name="Temporary review CI identity")
    principal.devices.add(device)
    principal.versions.add(version)
    token, credential = rotate_token(Actor(user.pk), project.pk, principal.pk)
    import hashlib
    content = (root / "examples" / "can" / "expected.hex").read_bytes()
    artifact, _ = upload(Actor(user.pk, principal.pk, credential.pk), project.pk, "synthetic-expected.hex", hashlib.sha256(content).hexdigest(), content)
    payload = {"project_id": str(project.pk), "items": [{"version_id": str(version.pk), "device_id": str(device.pk), "expected_artifact_id": str(artifact.pk), "actual_artifact_id": str(artifact.pk), "parameters": {"header_bytes": 0}}]}
    batch, _ = submit(Actor(user.pk, principal.pk, credential.pk), "restart-witness", payload)
    job = batch.jobs.get()
    private.write_text(json.dumps({"email": user.email, "password": password, "token": token, "project_id": str(project.pk),
                                  "payload": payload, "job_id": str(job.pk), "snapshot_sha256": checksum(job.snapshot)}), encoding="utf-8")
    print("Prepared isolated review user/inventory/input/queued job and a private restart witness. No execution.")
elif mode == "check":
    witness = json.loads(private.read_text(encoding="utf-8"))
    job = Job.objects.get(pk=witness["job_id"])
    assert checksum(job.snapshot) == witness["snapshot_sha256"] and job.state == "queued"
    assert User.objects.get(email=witness["email"]).is_active
    assert Device.objects.filter(project_id=witness["project_id"], source="simulated").count() == 1
    print("PASS: real PostgreSQL server restart preserved user, simulated inventory, queued job and immutable snapshot checksum.")
elif mode == "render":
    witness = json.loads(private.read_text(encoding="utf-8"))
    client = Client(HTTP_HOST="127.0.0.1")
    client.force_login(User.objects.get(email=witness["email"]))
    project_id = witness["project_id"]
    routes = {"jobs": reverse("section", args=[project_id, "runs"]), "queue": reverse("queue", args=[project_id]),
              "job": reverse("job_page", args=[project_id, witness["job_id"]]), "catalog": reverse("section", args=[project_id, "catalog"]),
              "workbench": reverse("workbench", args=[project_id])}
    output = root / ".local" / "m2a-preview"
    (output / "static").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(root / "web" / "static" / "lab.css", output / "static" / "lab.css")
    for name, route in routes.items():
        response = client.get(route)
        assert response.status_code == 200, (name, response.status_code)
        html = response.content.decode()
        html = html.replace('<main id="main" class="content">', '<main id="main" class="content"><div class="notice">Layout snapshot only · isolated simulated review data · forms inactive</div>')
        for target_name, target in routes.items():
            html = html.replace(target, f"/{target_name}.html")
        html = re.sub(r'<input type="hidden" name="csrfmiddlewaretoken"[^>]*>', '', html)
        html = re.sub(r'<form\b[^>]*>', '<div class="snapshot-form">', html).replace('</form>', '</div>')
        html = html.replace('<button ', '<button disabled ')
        (output / f"{name}.html").write_text(html, encoding="utf-8")
    print("Exported five labeled actual-template layout snapshots; no live form or execution evidence claimed.")
elif mode == "retire":
    witness = json.loads(private.read_text(encoding="utf-8"))
    user = User.objects.get(email=witness["email"])
    user.is_active = False
    user.set_unusable_password()
    user.session_epoch += 1
    user.save(update_fields=["is_active", "password", "session_epoch"])
    ServicePrincipal.objects.filter(owner=user).update(active=False)
    ServiceToken.objects.filter(principal__owner=user).update(revoked_at=timezone.now())
    private.unlink()
    print("Temporary review credentials retired. Review records preserved; no shared application accounts exist.")
else:
    raise SystemExit("Use prepare/check/render/retire.")
