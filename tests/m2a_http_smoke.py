"""Live same-origin/session and scoped-token HTTP smoke; isolated review credentials only."""
import http.cookiejar
import json
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request

root = Path(__file__).resolve().parent.parent
review = json.loads((root / ".local" / "m2a-review.json").read_text(encoding="utf-8"))
base = "http://127.0.0.1:8765"
jar = http.cookiejar.CookieJar()
browser = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def csrf():
    return next(cookie.value for cookie in jar if cookie.name == "csrftoken")


with browser.open(base + "/login/", timeout=10) as response:
    assert response.status == 200
request = urllib.request.Request(base + "/login/", data=urllib.parse.urlencode({"username": review["email"], "password": review["password"], "csrfmiddlewaretoken": csrf()}).encode(), headers={"Origin": base})
with browser.open(request, timeout=10) as response:
    assert "Lab overview" in response.read().decode()
with browser.open(base + f"/projects/{review['project_id']}/queue/", timeout=10) as response:
    assert "Queue an approved test" in response.read().decode()


def submit(payload, key):
    request = urllib.request.Request(base + "/api/v1/jobs", data=json.dumps(payload).encode(), headers={"Content-Type": "application/json", "Authorization": "Bearer " + review["token"], "Idempotency-Key": key})
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.status, json.loads(response.read())


status, first = submit(review["payload"], "live-http-witness")
assert status == 201 and all(job["state"] == "queued" and job["outcome"] is None for job in first["jobs"])
status, replay = submit(review["payload"], "live-http-witness")
assert status == 200 and first == replay
changed = {**review["payload"], "queue_seconds": 120}
try:
    submit(changed, "live-http-witness")
except urllib.error.HTTPError as error:
    assert error.code == 409
else:
    raise AssertionError("Conflicting key was accepted")
for route in ["/health/", "/ready/"]:
    with browser.open(base + route, timeout=10) as response:
        assert response.status == 200
request = urllib.request.Request(base + "/logout/", data=urllib.parse.urlencode({"csrfmiddlewaretoken": csrf()}).encode(), headers={"Origin": base})
with browser.open(request, timeout=10) as response:
    assert "Welcome back" in response.read().decode()
print("PASS: live PostgreSQL-backed session login/queue form, service-token queue/replay/conflict, health/readiness and POST logout. No execution.")
