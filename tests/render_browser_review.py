"""Export actual Django-rendered QA pages for layout inspection, not authentication evidence."""
import os
import sys
from pathlib import Path
import shutil

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root / "web"))
expected = root / ".local" / "browser-review.sqlite3"
if os.environ.get("LAB_DB") != "sqlite" or Path(os.environ.get("LAB_SQLITE_PATH", "")).resolve() != expected.resolve():
    raise SystemExit("Use the isolated browser-review SQLite database only.")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django
django.setup()
from django.test import Client
from django.urls import reverse
from lab.models import Project, User

output = root / ".local" / "preview"
(output / "static").mkdir(parents=True, exist_ok=True)
shutil.copyfile(root / "web" / "static" / "lab.css", output / "static" / "lab.css")
client = Client(HTTP_HOST="127.0.0.1")
user = User.objects.get(email="review@localhost.test")
client.force_login(user)
project = Project.objects.get(name="Portal review (temporary)")
for section in ["overview", "devices", "catalog", "runs", "results", "users", "audit"]:
    response = client.get(reverse("section", args=[project.pk, section]))
    if response.status_code != 200:
        raise SystemExit(f"Render failed: {section} {response.status_code}")
    html = response.content.decode()
    for key in ["overview", "devices", "catalog", "runs", "results", "users", "audit"]:
        html = html.replace(reverse("section", args=[project.pk, key]), f"/{key}.html")
    html = html.replace('<div class="page-heading">', '<div class="notice" role="status">Layout review snapshot · isolated temporary data · forms are inactive in this preview</div><div class="page-heading">')
    # Prevent review snapshots from submitting forms or displaying reusable CSRF values.
    import re
    html = re.sub(r'<input type="hidden" name="csrfmiddlewaretoken"[^>]*>', '', html)
    html = re.sub(r'<form\b[^>]*>', '<div class="snapshot-form">', html)
    html = html.replace('</form>', '</div>')
    html = html.replace('<button ', '<button disabled ')
    (output / f"{section}.html").write_text(html, encoding="utf-8")
print("Exported 7 rendered layout snapshots. These are not live authentication-flow evidence.")
