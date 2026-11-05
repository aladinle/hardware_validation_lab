"""Real loopback HTTP/CSRF/session smoke against the isolated QA server only."""
import http.cookiejar
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

root = Path(__file__).resolve().parent.parent
credentials = json.loads((root / ".local" / "browser-review.json").read_text(encoding="utf-8"))
base = "http://127.0.0.1:8765"
cookies = http.cookiejar.CookieJar()
client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookies))


def csrf():
    return next(cookie.value for cookie in cookies if cookie.name == "csrftoken")


def post(path, data, origin=base):
    request = urllib.request.Request(base + path, data=urllib.parse.urlencode(data).encode(), headers={"Origin": origin})
    return client.open(request, timeout=10)


with client.open(base + "/login/", timeout=10) as response:
    assert response.status == 200
with post("/login/", {"username": credentials["email"], "password": credentials["password"], "csrfmiddlewaretoken": csrf()}) as response:
    html = response.read().decode()
    assert response.status == 200 and "Lab overview" in html and "Portal review (temporary)" in html
    assert "No connected devices" in html and "No results yet" in html
    assert response.headers["Cache-Control"] == "no-store, private"
with client.open(base + "/static/lab.css", timeout=10) as response:
    assert response.status == 200 and "text/css" in response.headers["Content-Type"]
try:
    post("/logout/", {"csrfmiddlewaretoken": csrf()}, origin="null")
except urllib.error.HTTPError as exc:
    assert exc.code == 403
else:
    raise AssertionError("Null Origin was accepted")
with post("/logout/", {"csrfmiddlewaretoken": csrf()}) as response:
    assert response.status == 200 and "Welcome back" in response.read().decode()
print("PASS: live HTTP login, session dashboard, private-cache headers, CSS, null-Origin rejection, and POST logout.")
