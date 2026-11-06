"""M2A HTTP, ownership and database tests; PostgreSQL-only checks never pass on SQLite."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
from threading import Barrier
from unittest import skipUnless

from django.conf import settings
from django.core.management import call_command
from django.db import DatabaseError, close_old_connections, connection, connections, transaction
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from contracts.v1 import ContractError, parse_submission
from .models import (Artifact, AuditEvent, Batch, Device, DeviceGrant, Invitation, Job, Membership, Project, Role, Run,
                     ServicePrincipal, ServiceToken, TestApproval, TestDefinition, TestGrant, TestVersion, User)
from .services import invite
from .submissions import Actor, account_access, approval, checksum, edit_draft, publish, rotate_token, submit, upload, version_grant


class Fixture:
    @classmethod
    def prepare(cls):
        cls.project = Project.objects.create(name="M2A Alpha")
        cls.other = Project.objects.create(name="M2A Beta")
        cls.admin = User.objects.create_superuser(username="root@m2a.test", email="root@m2a.test", password="Tests-only-Meteor!2964")
        cls.operator = User.objects.create_user(username="operator@m2a.test", email="operator@m2a.test", password="Tests-only-Meteor!2964")
        cls.viewer = User.objects.create_user(username="viewer@m2a.test", email="viewer@m2a.test", password="Tests-only-Meteor!2964")
        cls.engineer = User.objects.create_user(username="engineer@m2a.test", email="engineer@m2a.test", password="Tests-only-Meteor!2964")
        cls.admin_member = Membership.objects.create(project=cls.project, user=cls.admin, role=Role.ADMIN)
        cls.member = Membership.objects.create(project=cls.project, user=cls.operator, role=Role.OPERATOR)
        cls.viewer_member = Membership.objects.create(project=cls.project, user=cls.viewer, role=Role.VIEWER)
        Membership.objects.create(project=cls.project, user=cls.engineer, role=Role.ENGINEER)
        cls.device = Device.objects.create(project=cls.project, name="Simulated station, offline", source="simulated", capabilities=["can_payload_files"])
        cls.foreign = Device.objects.create(project=cls.other, name="Secret Beta device", source="simulated", capabilities=["can_payload_files"])
        cls.definition = edit_draft(Actor(cls.admin.pk), cls.project.pk, {"name": "CAN contract", "header_bytes": 0})
        cls.version = publish(Actor(cls.admin.pk), cls.project.pk, cls.definition.pk)
        approval(Actor(cls.admin.pk), cls.project.pk, cls.version.pk, True)
        version_grant(Actor(cls.admin.pk), cls.project.pk, cls.member.pk, cls.version.pk, True)
        DeviceGrant.objects.create(membership=cls.member, device=cls.device)
        content = b"00 01 AA FF\n"
        cls.input, _ = upload(Actor(cls.operator.pk), cls.project.pk, "expected.hex", hashlib.sha256(content).hexdigest(), content)
        cls.payload = {"project_id": str(cls.project.pk), "items": [{"version_id": str(cls.version.pk), "device_id": str(cls.device.pk),
                     "expected_artifact_id": str(cls.input.pk), "actual_artifact_id": str(cls.input.pk), "parameters": {"header_bytes": 0}}]}


class M2ATests(Fixture, TestCase):
    @classmethod
    def setUpClass(cls):
        cls.storage = tempfile.TemporaryDirectory(prefix="m2a-inputs-")
        cls.config = override_settings(ARTIFACT_ROOT=Path(cls.storage.name))
        cls.config.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls.config.disable()
        cls.storage.cleanup()

    @classmethod
    def setUpTestData(cls):
        cls.prepare()

    def setUp(self):
        self.client.force_login(self.operator)

    def post(self, path, data, **headers):
        return self.client.post(path, json.dumps(data), content_type="application/json", **headers)

    def queue(self, data=None, key="request-1"):
        return self.post("/api/v1/jobs", data or self.payload, HTTP_IDEMPOTENCY_KEY=key)

    def test_workbench_validates_only_the_submitted_form(self):
        self.client.force_login(self.admin)
        url = reverse("workbench", args=[self.project.pk])
        for action in ("approve", "revoke", "grant", "ungrant", "publish"):
            with self.subTest(action=action):
                response = self.client.post(url, {"action": action, "version_id": self.version.pk,
                    "member_id": self.member.pk, "definition_id": self.definition.pk})
                self.assertEqual(response.status_code, 200)
                self.assertFalse(response.context["form"].is_bound)
                self.assertNotContains(response, "This field is required.")
        self.assertTrue(TestApproval.objects.filter(version=self.version, revoked_at__isnull=False).exists())
        self.assertFalse(TestGrant.objects.filter(membership=self.member, version=self.version).exists())
        self.assertEqual(self.definition.versions.count(), 2)
        before = TestDefinition.objects.count()
        for payload, field in (({}, "name"), ({"name": "Draft without header"}, "header_bytes")):
            with self.subTest(missing_field=field):
                response = self.client.post(url, {"action": "save", **payload})
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["form"].is_bound)
                self.assertEqual(response.context["form"].errors[field], ["This field is required."])
        self.assertEqual(TestDefinition.objects.count(), before)

    def test_real_http_queue_replay_conflict_and_no_execution(self):
        response = self.queue()
        self.assertEqual(response.status_code, 201, response.content)
        first = response.json()
        replay = self.queue()
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(first, replay.json())
        changed = deepcopy(self.payload)
        changed["queue_seconds"] = 120
        self.assertEqual(self.queue(changed).status_code, 409)
        self.assertEqual((Batch.objects.count(), Job.objects.count(), Run.objects.count()), (1, 1, 1))
        self.assertEqual(Job.objects.get().state, "queued")
        self.assertIsNone(first["jobs"][0]["outcome"])
        self.assertFalse(first["jobs"][0]["execution_available"])

    def test_defaults_key_order_are_canonical(self):
        self.queue()
        data = deepcopy(self.payload)
        data.update(software_commit=None, queue_seconds=3600)
        self.assertEqual(self.queue(data).status_code, 200)

    def test_entire_batch_rolls_back_with_bad_second_item(self):
        data = deepcopy(self.payload)
        data["items"].append({**data["items"][0], "device_id": str(self.foreign.pk)})
        self.assertEqual(self.queue(data).status_code, 403)
        self.assertEqual((Batch.objects.count(), Job.objects.count(), Run.objects.count()), (0, 0, 0))
        self.assertFalse(AuditEvent.objects.filter(action="batch.queued").exists())

    def test_viewer_and_unapproved_version_cannot_submit(self):
        self.client.force_login(self.viewer)
        self.assertEqual(self.queue().status_code, 403)
        self.client.force_login(self.operator)
        approval(Actor(self.admin.pk), self.project.pk, self.version.pk, False)
        self.assertEqual(self.queue().json()["error"]["code"], "UNAPPROVED_VERSION")

    def test_catalog_grant_is_not_execution_grant(self):
        TestGrant.objects.filter(membership=self.member).delete()
        TestGrant.objects.create(membership=self.member, test=self.definition)
        self.assertEqual(self.queue().json()["error"]["code"], "FORBIDDEN_TEST")

    def test_grant_member_and_device_revocation_deny_new_submissions(self):
        DeviceGrant.objects.filter(membership=self.member).delete()
        self.assertEqual(self.queue().json()["error"]["code"], "FORBIDDEN_DEVICE")
        self.member.active = False
        self.member.save()
        self.assertEqual(self.queue().status_code, 404)

    def test_header_override_capability_and_unknown_fields_rejected(self):
        data = deepcopy(self.payload)
        data["items"][0]["parameters"]["header_bytes"] = 16
        self.assertEqual(self.queue(data).status_code, 400)
        data = deepcopy(self.payload)
        data["shell"] = "anything"
        self.assertEqual(self.queue(data).status_code, 400)
        self.device.capabilities = []
        self.device.save()
        self.assertEqual(self.queue().json()["error"]["code"], "NO_MATCHING_CAPABILITY")

    def test_strict_contract_bounds_boolean_and_duplicate_json(self):
        for value in [True, -1, 999999]:
            data = deepcopy(self.payload)
            data["items"][0]["parameters"]["header_bytes"] = value
            self.assertEqual(self.queue(data).status_code, 400)
        self.assertEqual(self.client.post("/api/v1/jobs", '{"project_id":"a","project_id":"b"}', content_type="application/json").status_code, 400)

    def test_foreign_and_other_owner_input_denied(self):
        content = b"AA\n"
        other_input, _ = upload(Actor(self.engineer.pk), self.project.pk, "private.hex", hashlib.sha256(content).hexdigest(), content)
        data = deepcopy(self.payload)
        data["items"][0]["actual_artifact_id"] = str(other_input.pk)
        self.assertEqual(self.queue(data).status_code, 403)
        self.assertEqual(self.client.get(f"/api/v1/inputs/{other_input.pk}").status_code, 404)
        self.assertEqual(self.client.get(f"/api/v1/inputs/{self.input.pk}").content, b"00 01 AA FF\n")

    def test_upload_hash_size_name_and_duplicate_safety(self):
        path = f"/api/v1/projects/{self.project.pk}/inputs"
        data = b"AA BB\n"
        headers = {"HTTP_X_INPUT_NAME": "new.hex", "HTTP_X_CONTENT_SHA256": hashlib.sha256(data).hexdigest()}
        first = self.client.post(path, data, content_type="application/octet-stream", **headers)
        self.assertEqual(first.status_code, 201)
        second = self.client.post(path, data, content_type="application/octet-stream", **headers)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()["id"], second.json()["id"])
        headers["HTTP_X_INPUT_NAME"] = "../../escape.hex"
        self.assertEqual(self.client.post(path, data, content_type="application/octet-stream", **headers).status_code, 400)
        headers["HTTP_X_INPUT_NAME"] = "safe.hex"
        headers["HTTP_X_CONTENT_SHA256"] = "0" * 64
        self.assertEqual(self.client.post(path, data, content_type="application/octet-stream", **headers).status_code, 409)
        headers["HTTP_X_CONTENT_SHA256"] = hashlib.sha256(b"a" * (1024 * 1024 + 1)).hexdigest()
        self.assertEqual(self.client.post(path, b"a" * (1024 * 1024 + 1), content_type="application/octet-stream", **headers).status_code, 413)

    def test_published_snapshot_immutable_even_queryset_update(self):
        with self.assertRaises(ValueError):
            self.version.save()
        with self.assertRaises(DatabaseError), transaction.atomic():
            TestVersion.objects.filter(pk=self.version.pk).update(manifest_sha256="a" * 64)
        with self.assertRaises(DatabaseError), transaction.atomic():
            Artifact.objects.filter(pk=self.input.pk).update(sha256="a" * 64)

    def test_new_version_does_not_change_old_job_snapshot(self):
        self.assertEqual(self.queue().status_code, 201)
        original = Job.objects.get().snapshot
        edit_draft(Actor(self.admin.pk), self.project.pk, {"name": "Renamed later", "header_bytes": 16}, self.definition.pk)
        version = publish(Actor(self.admin.pk), self.project.pk, self.definition.pk)
        self.assertEqual(version.number, 2)
        self.assertFalse(version.approvals.exists())
        self.assertEqual(Job.objects.get().snapshot, original)
        self.assertIsNone(original["firmware"])

    def test_engineer_authoring_ownership_and_approval_separation(self):
        self.client.force_login(self.engineer)
        base = f"/api/v1/projects/{self.project.pk}"
        response = self.post(base + "/drafts", {"name": "Engineer draft", "header_bytes": 16})
        self.assertEqual(response.status_code, 201)
        version = self.post(base + f"/drafts/{response.json()['id']}/publish", {})
        self.assertEqual(version.status_code, 201)
        self.assertEqual(self.post(base + f"/versions/{version.json()['id']}/approval", {"approved": True}).status_code, 403)
        self.assertEqual(self.post(base + f"/drafts/{self.definition.pk}", {"name": "Take over", "header_bytes": 0}).status_code, 403)

    def service(self):
        principal = ServicePrincipal.objects.create(project=self.project, owner=self.operator, name="CI test only")
        principal.versions.add(self.version)
        principal.devices.add(self.device)
        secret, token = rotate_token(Actor(self.admin.pk), self.project.pk, principal.pk)
        return principal, secret, token

    def test_token_hash_rotation_revocation_and_no_session_fallback(self):
        principal, secret, token = self.service()
        self.assertNotEqual(token.digest, secret)
        path = f"/api/v1/catalog?project_id={self.project.pk}"
        self.assertEqual(self.client.get(path, HTTP_AUTHORIZATION="Bearer " + secret).status_code, 200)
        new_secret, _ = rotate_token(Actor(self.admin.pk), self.project.pk, principal.pk)
        self.assertEqual(self.client.get(path, HTTP_AUTHORIZATION="Bearer " + secret).status_code, 401)
        self.assertEqual(self.client.get(path, HTTP_AUTHORIZATION="Bearer " + new_secret).status_code, 200)
        principal.active = False
        principal.save()
        self.assertEqual(self.client.get(path, HTTP_AUTHORIZATION="Bearer " + new_secret).status_code, 401)

    def test_service_owner_revocation_and_scope_cannot_be_bypassed(self):
        principal, secret, token = self.service()
        client = Client()
        path = f"/api/v1/catalog?project_id={self.project.pk}"
        self.member.active = False
        self.member.save()
        self.assertEqual(client.get(path, HTTP_AUTHORIZATION="Bearer " + secret).status_code, 401)
        self.member.active = True
        self.member.save()
        principal.devices.clear()
        # Inputs uploaded by a service are scoped to that service, not merely its human owner.
        data = b"00\n"
        artifact, _ = upload(Actor(self.operator.pk, principal.pk, token.pk), self.project.pk, "service.hex", hashlib.sha256(data).hexdigest(), data)
        payload = deepcopy(self.payload)
        payload["items"][0].update(expected_artifact_id=str(artifact.pk), actual_artifact_id=str(artifact.pk))
        response = client.post("/api/v1/jobs", json.dumps(payload), content_type="application/json", HTTP_AUTHORIZATION="Bearer " + secret, HTTP_IDEMPOTENCY_KEY="service-request")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Job.objects.count(), 0)

    def test_service_token_expiry(self):
        principal, secret, token = self.service()
        ServiceToken.objects.filter(pk=token.pk).update(expires_at=timezone.now())
        self.assertEqual(self.client.get(f"/api/v1/catalog?project_id={self.project.pk}", HTTP_AUTHORIZATION="Bearer " + secret).status_code, 401)

    def test_api_session_csrf_and_token_cannot_manage_access(self):
        browser = Client(enforce_csrf_checks=True)
        browser.force_login(self.operator)
        self.assertEqual(browser.post("/api/v1/jobs", json.dumps(self.payload), content_type="application/json", HTTP_IDEMPOTENCY_KEY="csrf").status_code, 403)
        browser.get(reverse("login"))
        token = browser.cookies["csrftoken"].value
        self.assertEqual(browser.post("/api/v1/jobs", json.dumps(self.payload), content_type="application/json", HTTP_IDEMPOTENCY_KEY="csrf", HTTP_X_CSRFTOKEN=token).status_code, 201)
        principal, secret, _ = self.service()
        path = f"/api/v1/projects/{self.project.pk}/versions/{self.version.pk}/approval"
        self.assertEqual(self.post(path, {"approved": True}, HTTP_AUTHORIZATION="Bearer " + secret).status_code, 403)

    def test_revoking_sessions_and_reactivation_cannot_revive_old_cookie(self):
        browser = Client()
        browser.force_login(self.operator)
        account_access(Actor(self.admin.pk), self.operator.pk, "revoke_sessions")
        self.assertEqual(browser.get(reverse("project", args=[self.project.pk])).status_code, 302)
        browser.force_login(User.objects.get(pk=self.operator.pk))
        account_access(Actor(self.admin.pk), self.operator.pk, "deactivate")
        account_access(Actor(self.admin.pk), self.operator.pk, "reactivate")
        self.assertEqual(browser.get(reverse("project", args=[self.project.pk])).status_code, 302)
        self.assertEqual(AuditEvent.objects.filter(action__startswith="account.").count(), 3)

    def test_project_admin_cannot_deactivate_global_account(self):
        Membership.objects.filter(project=self.project, user=self.engineer).update(role=Role.ADMIN)
        self.client.force_login(self.engineer)
        self.assertEqual(self.post(f"/api/v1/accounts/{self.operator.pk}", {"action": "deactivate"}).status_code, 403)

    def test_invitation_revocation_blocks_acceptance(self):
        secret = invite(self.admin, self.project, "new@m2a.test", Role.OPERATOR)
        invitation = Invitation.objects.get(token_hash=hashlib.sha256(secret.encode()).hexdigest())
        self.client.force_login(self.admin)
        self.assertEqual(self.post(f"/api/v1/projects/{self.project.pk}/invitations/{invitation.pk}/revoke", {}).status_code, 200)
        self.client.logout()
        response = self.client.post(reverse("accept"), {"token": secret, "password": "Tests-only-Aurora!8427", "confirm_password": "Tests-only-Aurora!8427"})
        self.assertContains(response, "Invitation unavailable")

    def test_job_history_direct_identifier_and_portal_forms(self):
        response = self.queue()
        job_id = response.json()["jobs"][0]["id"]
        self.assertEqual(self.client.get(f"/api/v1/jobs/{job_id}").status_code, 200)
        for name in ["queue", "input_upload"]:
            self.assertEqual(self.client.get(reverse(name, args=[self.project.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("job_page", args=[self.project.pk, job_id])).status_code, 200)
        self.assertContains(self.client.get(reverse("section", args=[self.project.pk, "runs"])), "Queued")
        self.client.force_login(self.engineer)
        self.assertEqual(self.client.get(f"/api/v1/jobs/{job_id}").status_code, 404)
        self.assertEqual(self.client.get(reverse("workbench", args=[self.project.pk])).status_code, 200)

    def test_anonymous_api_and_health_readiness(self):
        self.client.logout()
        self.assertEqual(self.client.get("/api/v1/jobs").status_code, 401)
        self.assertEqual(self.client.get("/health/").status_code, 200)
        self.assertEqual(self.client.get("/ready/").status_code, 200)

    def test_ungranted_published_version_is_hidden_from_catalog(self):
        second = publish(Actor(self.admin.pk), self.project.pk, self.definition.pk)
        catalog = self.client.get(f"/api/v1/catalog?project_id={self.project.pk}")
        self.assertEqual(catalog.status_code, 200)
        self.assertNotIn(str(second.pk), catalog.content.decode())
        response = self.client.get(reverse("section", args=[self.project.pk, "catalog"]))
        self.assertNotContains(response, str(second.pk))

    def test_service_submit_success_and_idempotency_is_principal_scoped(self):
        principal, secret, token = self.service()
        data = b"AA\n"
        artifact, _ = upload(Actor(self.operator.pk, principal.pk, token.pk), self.project.pk, "owned.hex", hashlib.sha256(data).hexdigest(), data)
        payload = deepcopy(self.payload)
        payload["items"][0].update(expected_artifact_id=str(artifact.pk), actual_artifact_id=str(artifact.pk))
        client = Client(enforce_csrf_checks=True)
        response = client.post("/api/v1/jobs", json.dumps(payload), content_type="application/json", HTTP_AUTHORIZATION="Bearer " + secret, HTTP_IDEMPOTENCY_KEY="shared-key")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(self.queue(key="shared-key").status_code, 201)
        self.assertEqual(Batch.objects.count(), 2)

    def test_job_detail_loses_access_after_version_grant_revocation(self):
        job_id = self.queue().json()["jobs"][0]["id"]
        version_grant(Actor(self.admin.pk), self.project.pk, self.member.pk, self.version.pk, False)
        self.assertEqual(self.client.get(f"/api/v1/jobs/{job_id}").status_code, 404)

    def test_catalog_grant_management_still_works_with_multiple_version_grants(self):
        second = publish(Actor(self.admin.pk), self.project.pk, self.definition.pk)
        version_grant(Actor(self.admin.pk), self.project.pk, self.member.pk, second.pk, True)
        self.client.force_login(self.admin)
        response = self.client.post(reverse("change_grant", args=[self.project.pk, self.member.pk]), {"kind": "test", "record": str(self.definition.pk), "granted": "on"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(TestGrant.objects.filter(membership=self.member).count(), 3)


@skipUnless(connection.vendor == "postgresql", "Requires real PostgreSQL; SQLite is not concurrency evidence.")
class PostgreSQLSubmissionTests(Fixture, TransactionTestCase):
    def setUp(self):
        self.storage = tempfile.TemporaryDirectory(prefix="m2a-pg-inputs-")
        self.config = override_settings(ARTIFACT_ROOT=Path(self.storage.name))
        self.config.enable()
        self.prepare()

    def tearDown(self):
        self.config.disable()
        self.storage.cleanup()

    def test_two_competing_connections_create_one_submission(self):
        barrier = Barrier(2)
        def send():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                batch, created = submit(Actor(self.operator.pk), "concurrent-key", self.payload)
                return str(batch.pk), created
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: send(), range(2)))
        self.assertEqual(results[0][0], results[1][0])
        self.assertEqual(sorted(result[1] for result in results), [False, True])
        self.assertEqual((Batch.objects.count(), Job.objects.count(), Run.objects.count()), (1, 1, 1))

    def test_new_database_connection_preserves_queued_snapshot(self):
        batch, _ = submit(Actor(self.operator.pk), "restart-test", self.payload)
        job_id = batch.jobs.get().pk
        original = Job.objects.get(pk=job_id).snapshot
        connections.close_all()
        self.assertEqual(Job.objects.get(pk=job_id).snapshot, original)
        self.assertEqual(Job.objects.get(pk=job_id).state, "queued")
