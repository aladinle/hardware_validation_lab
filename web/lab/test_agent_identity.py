"""M2B.1 identity/contact checks. No test starts a hardware workload."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import StringIO
import json
from pathlib import Path
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from unittest import skipUnless
import uuid

from django.db import IntegrityError, close_old_connections, connection, connections, transaction
from django.test import Client, SimpleTestCase, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from agent.__main__ import main
from agent.client import enroll_client, load_state, replace_credential, save_new
from agent.transport import AgentError, Transport, server_url
from contracts.agents_v1 import AGENT_VERSION, parse_heartbeat, parse_idle_reply
from contracts.v1 import ContractError
from .agent_services import create_agent, enroll, manage_agent
from .models import (Agent, AgentCredential, AgentDevice, AgentEnrollment, AgentHeartbeat, AuditEvent,
                     Device, Job, Membership, Project, Role, ServicePrincipal, ServiceToken, User)
from .services import digest
from .submissions import Actor, Rejected


class AgentIdentityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.project = Project.objects.create(name="Identity Alpha")
        cls.other = Project.objects.create(name="Identity Beta")
        cls.admin = User.objects.create_user(username="manager@agent.test", email="manager@agent.test", password="Tests-only-Nova!6937")
        cls.viewer = User.objects.create_user(username="viewer@agent.test", email="viewer@agent.test", password="Tests-only-Nova!6937")
        cls.member = Membership.objects.create(project=cls.project, user=cls.admin, role=Role.ADMIN)
        Membership.objects.create(project=cls.project, user=cls.viewer, role=Role.VIEWER)
        cls.device = Device.objects.create(project=cls.project, name="Synthetic offline inventory", source="simulated")
        cls.device2 = Device.objects.create(project=cls.project, name="Second offline inventory", source="simulated")
        cls.foreign = Device.objects.create(project=cls.other, name="Other project inventory", source="simulated")

    def setUp(self):
        self.client.force_login(self.admin)

    def post(self, route, value, token=None, scheme="Bearer", client=None):
        headers = {"HTTP_AUTHORIZATION": scheme + " " + token} if token else {}
        return (client or self.client).post(route, json.dumps(value), content_type="application/json", **headers)

    def create(self, device=None):
        return create_agent(Actor(self.admin.pk), self.project.pk, "Native agent test", [str((device or self.device).pk)])

    def enrollment(self, document):
        return {"schema_version": 1, "agent_version": AGENT_VERSION, "platform": "Windows", "device_ids": document["device_ids"]}

    def enroll(self, agent, document):
        response = self.post(f"/api/v1/agents/{agent.pk}/enroll", self.enrollment(document), document["token"], "Enrollment")
        self.assertEqual(response.status_code, 200)
        return response.json()

    def message(self, credential):
        return {"schema_version": 1, "heartbeat_id": str(uuid.uuid4()), "sent_at": timezone.now().isoformat(),
                "agent_version": AGENT_VERSION, "platform": "Windows", "device_ids": credential["device_ids"],
                "observations": [], "active_execution_id": None, "ready": False}

    def test_administrator_controlled_enrollment_and_hashed_credentials(self):
        route = f"/api/v1/projects/{self.project.pk}/agents"
        response = self.post(route, {"name": "Windows process", "device_ids": [str(self.device.pk)]})
        self.assertEqual(response.status_code, 201)
        invitation = response.json()
        self.assertTrue(invitation["token"] != AgentEnrollment.objects.get().digest)
        agent = Agent.objects.get()
        credential = self.enroll(agent, invitation)
        self.assertTrue(credential["token"] != AgentCredential.objects.get().digest)
        self.assertTrue(AgentEnrollment.objects.get().consumed_at is not None)
        self.assertIn("no-store", response["Cache-Control"])
        audit_text = str(list(AuditEvent.objects.values("action", "target")))
        self.assertTrue(invitation["token"] not in audit_text and credential["token"] not in audit_text)

    def test_viewer_cross_project_and_ci_cannot_enroll_or_manage(self):
        route = f"/api/v1/projects/{self.project.pk}/agents"
        self.client.force_login(self.viewer)
        self.assertEqual(self.post(route, {"name": "Denied", "device_ids": [str(self.device.pk)]}).status_code, 403)
        self.assertEqual(self.client.get(reverse("agents", args=[self.project.pk])).status_code, 404)
        self.client.force_login(self.admin)
        self.assertEqual(self.post(f"/api/v1/projects/{self.other.pk}/agents", {"name": "Denied", "device_ids": [str(self.foreign.pk)]}).status_code, 404)
        service = ServicePrincipal.objects.create(project=self.project, owner=self.admin, name="CI cannot enroll agents")
        secret = "test-only-ci-secret"
        ServiceToken.objects.create(principal=service, digest=digest(secret), expires_at=timezone.now() + timedelta(hours=1))
        self.assertEqual(self.post(route, {"name": "Denied", "device_ids": [str(self.device.pk)]}, secret).status_code, 403)
        self.assertEqual(Agent.objects.count(), 0)

    def test_admin_session_csrf_required_but_explicit_agent_authority_is_separate(self):
        browser = Client(enforce_csrf_checks=True)
        browser.force_login(self.admin)
        route = f"/api/v1/projects/{self.project.pk}/agents"
        data = {"name": "CSRF test", "device_ids": [str(self.device.pk)]}
        self.assertEqual(self.post(route, data, client=browser).status_code, 403)
        browser.get(reverse("login"))
        response = browser.post(route, json.dumps(data), content_type="application/json", HTTP_X_CSRFTOKEN=browser.cookies["csrftoken"].value)
        self.assertEqual(response.status_code, 201)
        invitation = response.json()
        native = Client(enforce_csrf_checks=True)
        self.assertEqual(self.post(f"/api/v1/agents/{invitation['agent_id']}/enroll", self.enrollment(invitation), invitation["token"], "Enrollment", native).status_code, 200)

    def test_wrong_project_disabled_and_duplicate_device_scope_rejected_atomically(self):
        route = f"/api/v1/projects/{self.project.pk}/agents"
        for values in [[str(self.foreign.pk)], [str(self.device.pk), str(self.device.pk)]]:
            response = self.post(route, {"name": "Denied scope", "device_ids": values})
            self.assertIn(response.status_code, (400, 403))
        self.assertEqual(Agent.objects.count(), 0)
        Device.objects.filter(pk=self.device.pk).update(enabled=False)
        self.assertEqual(self.post(route, {"name": "Disabled", "device_ids": [str(self.device.pk)]}).status_code, 403)

    def test_one_active_agent_per_device_and_db_constraint(self):
        agent, invitation = self.create()
        route = f"/api/v1/projects/{self.project.pk}/agents"
        self.assertEqual(self.post(route, {"name": "Conflict", "device_ids": [str(self.device.pk)]}).status_code, 409)
        other = Agent.objects.create(project=self.project, name="Direct constraint check", created_by=self.admin)
        with self.assertRaises(IntegrityError), transaction.atomic():
            AgentDevice.objects.create(agent=other, device=self.device)

    def test_single_use_expired_and_issuer_revoked_enrollment(self):
        agent, document = self.create()
        self.enroll(agent, document)
        self.assertEqual(self.post(f"/api/v1/agents/{agent.pk}/enroll", self.enrollment(document), document["token"], "Enrollment").status_code, 401)
        second, ticket = self.create(self.device2)
        AgentEnrollment.objects.filter(agent=second).update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.post(f"/api/v1/agents/{second.pk}/enroll", self.enrollment(ticket), ticket["token"], "Enrollment").status_code, 401)
        ticket = manage_agent(Actor(self.admin.pk), self.project.pk, second.pk, "reenroll")
        Membership.objects.filter(pk=self.member.pk).update(active=False)
        self.assertEqual(self.post(f"/api/v1/agents/{second.pk}/enroll", self.enrollment(ticket), ticket["token"], "Enrollment").status_code, 401)

    def test_no_cookie_ci_or_enrollment_credential_fallback_for_heartbeat(self):
        agent, document = self.create()
        credential = self.enroll(agent, document)
        route = f"/api/v1/agents/{agent.pk}/heartbeat"
        message = self.message(credential)
        for token in (None, "invalid", document["token"], "test-only-ci-secret"):
            self.assertEqual(self.post(route, message, token).status_code, 401)
        self.assertIsNone(Agent.objects.get(pk=agent.pk).last_contact_at)

    def test_cross_agent_credential_and_device_spoof_are_rejected(self):
        agent, ticket = self.create()
        credential = self.enroll(agent, ticket)
        other, ticket2 = self.create(self.device2)
        credential2 = self.enroll(other, ticket2)
        message = self.message(credential)
        self.assertEqual(self.post(f"/api/v1/agents/{other.pk}/heartbeat", message, credential["token"]).status_code, 401)
        message["device_ids"] = credential2["device_ids"]
        self.assertEqual(self.post(f"/api/v1/agents/{agent.pk}/heartbeat", message, credential["token"]).status_code, 403)
        self.assertEqual(AgentHeartbeat.objects.count(), 0)

    def test_contact_is_idle_and_does_not_connect_inventory_or_dispatch_jobs(self):
        agent, ticket = self.create()
        credential = self.enroll(agent, ticket)
        message = self.message(credential)
        response = self.post(f"/api/v1/agents/{agent.pk}/heartbeat", message, credential["token"])
        self.assertEqual(response.status_code, 200)
        reply = response.json()
        parse_idle_reply(reply, str(agent.pk), message["heartbeat_id"])
        self.assertIsNone(reply["assignment"])
        self.assertFalse(reply["execution_available"])
        self.assertEqual(reply["devices_connected"], [])
        self.assertEqual(Job.objects.count(), 0)
        self.assertEqual(Agent.objects.get(pk=agent.pk).reported_platform, "Windows")
        inventory = self.client.get(f"/api/v1/catalog?project_id={self.project.pk}").json()["devices"]
        self.assertTrue(all(not device["online"] and not device["ready"] for device in inventory))
        self.assertEqual(Device.objects.get(pk=self.device.pk).capabilities, self.device.capabilities)
        for suffix in ("claim", "result", "events", "cancel"):
            self.assertEqual(self.post(f"/api/v1/agents/{agent.pk}/{suffix}", {}, credential["token"]).status_code, 404)

    def test_duplicate_heartbeat_does_not_refresh_contact_and_conflict_is_409(self):
        agent, ticket = self.create()
        credential = self.enroll(agent, ticket)
        message = self.message(credential)
        route = f"/api/v1/agents/{agent.pk}/heartbeat"
        first = self.post(route, message, credential["token"]).json()
        second = self.post(route, message, credential["token"]).json()
        self.assertTrue(second["replayed"])
        self.assertEqual(first["last_contact_at"], second["last_contact_at"])
        message["platform"] = "Linux"
        self.assertEqual(self.post(route, message, credential["token"]).status_code, 409)
        self.assertEqual(AgentHeartbeat.objects.count(), 1)

    def test_rotation_revocation_expiry_and_disabling_are_immediate(self):
        agent, ticket = self.create()
        credential = self.enroll(agent, ticket)
        route = f"/api/v1/agents/{agent.pk}/heartbeat"
        rotated = manage_agent(Actor(self.admin.pk), self.project.pk, agent.pk, "rotate")
        self.assertEqual(self.post(route, self.message(credential), credential["token"]).status_code, 401)
        self.assertEqual(self.post(route, self.message(rotated), rotated["token"]).status_code, 200)
        AgentCredential.objects.filter(agent=agent, revoked_at=None).update(expires_at=timezone.now())
        self.assertEqual(self.post(route, self.message(rotated), rotated["token"]).status_code, 401)
        new = manage_agent(Actor(self.admin.pk), self.project.pk, agent.pk, "rotate")
        manage_agent(Actor(self.admin.pk), self.project.pk, agent.pk, "disable")
        self.assertEqual(self.post(route, self.message(new), new["token"]).status_code, 401)

    def test_device_disable_or_binding_removal_blocks_contact(self):
        agent, ticket = self.create()
        credential = self.enroll(agent, ticket)
        route = f"/api/v1/agents/{agent.pk}/heartbeat"
        Device.objects.filter(pk=self.device.pk).update(enabled=False)
        self.assertEqual(self.post(route, self.message(credential), credential["token"]).status_code, 403)
        Device.objects.filter(pk=self.device.pk).update(enabled=True)
        AgentDevice.objects.filter(agent=agent).update(active=False)
        self.assertEqual(self.post(route, self.message(credential), credential["token"]).status_code, 403)

    def test_scope_change_requires_new_enrollment_and_invalidates_old_token(self):
        agent, ticket = self.create()
        credential = self.enroll(agent, ticket)
        new_ticket = manage_agent(Actor(self.admin.pk), self.project.pk, agent.pk, "set_devices", [str(self.device2.pk)])
        route = f"/api/v1/agents/{agent.pk}/heartbeat"
        self.assertEqual(self.post(route, self.message(credential), credential["token"]).status_code, 401)
        fresh = self.enroll(agent, new_ticket)
        self.assertEqual(fresh["device_ids"], [str(self.device2.pk)])
        self.assertEqual(self.post(route, self.message(fresh), fresh["token"]).status_code, 200)

    def test_claimed_execution_readiness_discovery_and_extra_fields_fail_closed(self):
        agent, ticket = self.create()
        credential = self.enroll(agent, ticket)
        route = f"/api/v1/agents/{agent.pk}/heartbeat"
        for key, value in [("ready", True), ("observations", [{"connected": True}]), ("active_execution_id", str(uuid.uuid4())), ("command", "anything"), ("schema_version", True)]:
            message = self.message(credential)
            message[key] = value
            self.assertEqual(self.post(route, message, credential["token"]).status_code, 400)
        self.assertEqual(AgentHeartbeat.objects.count(), 0)

    def test_malformed_large_protocol_does_not_record_contact(self):
        agent, ticket = self.create()
        credential = self.enroll(agent, ticket)
        route = f"/api/v1/agents/{agent.pk}/heartbeat"
        response = self.client.post(route, '{"schema_version":1,"schema_version":1}', content_type="application/json", HTTP_AUTHORIZATION="Bearer " + credential["token"])
        self.assertEqual(response.status_code, 400)
        response = self.client.post(route, b" " * 65537, content_type="application/json", HTTP_AUTHORIZATION="Bearer " + credential["token"])
        self.assertEqual(response.status_code, 413)
        self.assertEqual(AgentHeartbeat.objects.count(), 0)

    def test_admin_portal_download_and_list_do_not_expose_stored_secrets(self):
        route = reverse("agents", args=[self.project.pk])
        response = self.client.post(route, {"action": "create", "name": "Downloaded enrollment", "devices": [str(self.device.pk)]})
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response["Content-Disposition"])
        ticket = response.json()
        listing = self.client.get(route)
        self.assertContains(listing, "Awaiting enrollment")
        self.assertTrue(ticket["token"] not in listing.content.decode())
        self.assertEqual(self.client.get(f"/api/v1/projects/{self.other.pk}/agents").status_code, 404)


class AgentClientTests(SimpleTestCase):
    def credential(self, enrollment=False):
        return {"schema_version": 1, "agent_id": str(uuid.uuid4()), "project_id": str(uuid.uuid4()), "device_ids": [str(uuid.uuid4())],
                "credential_kind": "enrollment" if enrollment else "agent", "token": ("hve_" if enrollment else "hva_") + "a" * 43,
                "expires_at": (timezone.now() + timedelta(hours=1)).isoformat()}

    def test_transport_requires_explicit_loopback_http_or_verified_https_origin(self):
        for value in ["http://example.test", "http://localhost.attacker.test", "http://0.0.0.0", "https://user:secret@example.test", "https://example.test/path", "file:///tmp/test", "http://127.0.0.1/?token=secret"]:
            with self.assertRaises(AgentError):
                server_url(value)
        self.assertEqual(server_url("http://127.0.0.1:8765/"), "http://127.0.0.1:8765")
        self.assertEqual(server_url("https://lab.example.test"), "https://lab.example.test")

    def test_tls_environment_failure_is_safe_and_does_not_change_verification(self):
        with patch("agent.transport.ssl.create_default_context", side_effect=PermissionError("private environment hook")):
            with self.assertRaises(AgentError) as failure:
                Transport("http://127.0.0.1:8765")
        self.assertTrue("private environment hook" not in str(failure.exception))

    def test_existing_private_state_is_preserved_without_network_call(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text("preserve", encoding="utf-8")
            with patch("agent.client.Transport") as transport, self.assertRaises(AgentError):
                enroll_client("http://127.0.0.1:8765", "unused", path)
            transport.assert_not_called()
            self.assertEqual(path.read_text(), "preserve")

    def test_rotation_can_replace_expired_state_but_not_scope_or_existing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            old = self.credential()
            new = deepcopy(old)
            old["expires_at"] = (timezone.now() - timedelta(seconds=1)).isoformat()
            state = Path(directory) / "old.json"
            document = Path(directory) / "rotated.json"
            output = Path(directory) / "new.json"
            save_new(state, {**old, "server_url": "http://127.0.0.1:8765"})
            save_new(document, new)
            replace_credential(state, document, output)
            self.assertEqual(load_state(output)[0]["agent_id"], new["agent_id"])
            with self.assertRaises(AgentError):
                replace_credential(state, document, output)
            new["project_id"] = str(uuid.uuid4())
            document.write_text(json.dumps(new))
            with self.assertRaises(AgentError):
                replace_credential(state, document, Path(directory) / "invalid.json")

    def test_idle_contract_rejects_server_assignment_and_cli_has_bounded_loop(self):
        with self.assertRaises(ContractError):
            parse_idle_reply({"schema_version": 1}, str(uuid.uuid4()), str(uuid.uuid4()))
        with patch("sys.stderr", new_callable=StringIO), patch("agent.__main__.contact_once") as contact:
            self.assertEqual(main(["heartbeat", "--state-file", "unused", "--count", "1001"]), 2)
            contact.assert_not_called()

    def test_untrusted_heartbeat_fields_reject_invalid_timestamp_and_schema(self):
        message = {"schema_version": 1, "heartbeat_id": str(uuid.uuid4()), "sent_at": "2026-11-05T12:00:00",
                   "agent_version": AGENT_VERSION, "platform": "Windows", "device_ids": [str(uuid.uuid4())],
                   "observations": [], "ready": False, "active_execution_id": None}
        with self.assertRaises(ContractError):
            parse_heartbeat(message)

    def test_real_transport_refuses_redirect_without_forwarding_credentials(self):
        paths = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                paths.append(self.path)
                self.rfile.read(int(self.headers.get("Content-Length", 0)))
                self.send_response(302)
                self.send_header("Location", "/sink")
                self.end_headers()

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with self.assertRaises(AgentError):
                Transport(f"http://127.0.0.1:{server.server_port}").post(f"/api/v1/agents/{uuid.uuid4()}/heartbeat", {}, "test-only-transport-secret")
            self.assertEqual(len(paths), 1)
            self.assertTrue("/sink" not in paths)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


    def test_real_transport_response_bounds_and_safe_errors(self):
        class Handler(BaseHTTPRequestHandler):
            response_kind = "oversized"

            def log_message(self, *args):
                pass

            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length", 0)))
                if self.response_kind == "oversized":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(b" " * 65537)
                else:
                    self.send_response(403)
                    self.end_headers()
                    self.wfile.write(b"untrusted error: test-only-transport-secret")

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            transport = Transport(f"http://127.0.0.1:{server.server_port}")
            for kind in ["oversized", "forbidden"]:
                Handler.response_kind = kind
                with self.assertRaises(AgentError) as error:
                    transport.post(f"/api/v1/agents/{uuid.uuid4()}/heartbeat", {}, "test-only-transport-secret")
                self.assertTrue("test-only-transport-secret" not in str(error.exception))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


@skipUnless(connection.vendor == "postgresql", "Single-use concurrency must be tested on real PostgreSQL.")
class EnrollmentConcurrencyTests(TransactionTestCase):
    def test_two_enrollment_connections_cannot_consume_one_ticket_twice(self):
        project = Project.objects.create(name="Enrollment concurrency")
        administrator = User.objects.create_user(username="enrollment@race.test", email="enrollment@race.test")
        Membership.objects.create(project=project, user=administrator, role=Role.ADMIN)
        device = Device.objects.create(project=project, name="Synthetic concurrency scope", source="simulated")
        agent, ticket = create_agent(Actor(administrator.pk), project.pk, "One ticket", [str(device.pk)])
        payload = {"schema_version": 1, "agent_version": AGENT_VERSION, "platform": "Windows", "device_ids": ticket["device_ids"]}
        barrier = threading.Barrier(2)
        def consume():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                try:
                    enroll(agent.pk, ticket["token"], payload)
                    return 200
                except Rejected as exc:
                    return exc.status
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as executor:
            statuses = list(executor.map(lambda _: consume(), range(2)))
        self.assertEqual(sorted(statuses), [200, 401])
        self.assertEqual(AgentCredential.objects.filter(agent=agent, revoked_at=None).count(), 1)
        self.assertEqual(AgentEnrollment.objects.filter(agent=agent, consumed_at__isnull=False).count(), 1)
