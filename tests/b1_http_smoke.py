"""Live HTTP + installed native process, with secrets kept in private files/in-memory."""
import http.cookiejar
import json
from pathlib import Path
import subprocess
import sys
import urllib.parse
import urllib.request

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))
from agent.client import save_new

review = json.loads((root / ".local/b1-review.json").read_text(encoding="utf-8"))
origin = "http://127.0.0.1:8765"
jar = http.cookiejar.CookieJar()
browser = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(jar))
native = root / ".local/b1-agent-venv/Scripts/hvl-agent.exe"


def csrf():
    return next(cookie.value for cookie in jar if cookie.name == "csrftoken")


def admin_post(path, payload):
    request = urllib.request.Request(origin + path, data=json.dumps(payload).encode(), headers={"Origin": origin, "Content-Type": "application/json", "X-CSRFToken": csrf()})
    with browser.open(request, timeout=10) as response:
        return json.loads(response.read())


def run_cli(args, expected=0):
    result = subprocess.run([str(native), *args], cwd=root / ".local", capture_output=True, text=True, timeout=20)
    assert result.returncode == expected, "Unexpected native process result; no credentials are printed."
    for secret in secrets:
        assert secret not in result.stdout + result.stderr, "Native output exposed a secret."
    return [json.loads(line) for line in result.stdout.splitlines()]


secrets = [review["password"]]
with browser.open(origin + "/login/", timeout=10) as response:
    assert response.status == 200
request = urllib.request.Request(origin + "/login/", data=urllib.parse.urlencode({"username": review["email"], "password": review["password"], "csrfmiddlewaretoken": csrf()}).encode(), headers={"Origin": origin})
with browser.open(request, timeout=10) as response:
    assert response.status == 200
base = f"/api/v1/projects/{review['project_id']}/agents"
ticket = admin_post(base, {"name": "Native Windows contact review", "device_ids": [review["device_id"]]})
secrets.append(ticket["token"])
invitation = root / ".local/b1-enrollment.json"
state = root / ".local/b1-state.json"
save_new(invitation, ticket)
run_cli(["enroll", "--server", origin, "--invitation-file", str(invitation), "--state-file", str(state)])
credential = json.loads(state.read_text(encoding="utf-8"))
secrets.append(credential["token"])
contact = run_cli(["heartbeat", "--state-file", str(state), "--count", "2", "--interval", "1"])
assert len(contact) == 2 and all(message["assignment"] is None and not message["execution_available"] and not message["devices_ready"] for message in contact)
rotated = admin_post(base + "/" + ticket["agent_id"], {"action": "rotate"})
secrets.append(rotated["token"])
rotated_file = root / ".local/b1-rotated.json"
new_state = root / ".local/b1-state-rotated.json"
save_new(rotated_file, rotated)
run_cli(["heartbeat", "--state-file", str(state)], expected=2)
run_cli(["install-credential", "--state-file", str(state), "--credential-file", str(rotated_file), "--output-file", str(new_state)])
run_cli(["heartbeat", "--state-file", str(new_state)])
admin_post(base + "/" + ticket["agent_id"], {"action": "revoke"})
run_cli(["heartbeat", "--state-file", str(new_state)], expected=2)
with browser.open(origin + base, timeout=10) as response:
    records = json.loads(response.read())["agents"]
    assert len(records) == 1 and records[0]["last_contact_at"] is not None and records[0]["reported_platform"] == "Windows"
    assert not records[0]["devices_ready"] and not records[0]["execution_available"]
request = urllib.request.Request(origin + "/logout/", data=urllib.parse.urlencode({"csrfmiddlewaretoken": csrf()}).encode(), headers={"Origin": origin})
with browser.open(request, timeout=10) as response:
    assert response.status == 200
print("PASS: live administrator enrollment, clean installed Windows agent process, two idle heartbeats, rotation/old-token denial, replacement/new-token contact, revocation denial and no credential output. No assignment or hardware work.")
