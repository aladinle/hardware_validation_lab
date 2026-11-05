import logging
from datetime import timedelta
from io import StringIO
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from .logging import RedactRecoveryFilter
from .models import AuditEvent, Device, DeviceGrant, Invitation, Membership, Project, Role, TestDefinition, TestGrant
from .services import digest, invite

User = get_user_model()
# Test-only password, never a bundled account or bootstrap default.
PASSWORD = "Testing-only-Orbit!4827"


class PortalTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = Project.objects.create(name="Project Alpha")
        cls.b = Project.objects.create(name="Project Beta")
        cls.users = {}
        cls.members = {}
        for role in Role.values:
            user = User.objects.create_user(username=f"{role}@example.test", email=f"{role}@example.test", password=PASSWORD)
            cls.users[role] = user
            cls.members[role] = Membership.objects.create(user=user, project=cls.a, role=role)
        cls.platform = User.objects.create_superuser(username="platform@example.test", email="platform@example.test", password=PASSWORD)
        cls.foreign_user = User.objects.create_user(username="other@example.test", email="other@example.test", password=PASSWORD)
        cls.foreign_member = Membership.objects.create(user=cls.foreign_user, project=cls.b, role=Role.ADMIN)
        cls.device = Device.objects.create(project=cls.a, name="Alpha inventory only")
        cls.hidden_device = Device.objects.create(project=cls.a, name="Restricted Alpha hardware")
        cls.foreign_device = Device.objects.create(project=cls.b, name="Secret Beta hardware")
        cls.test = TestDefinition.objects.create(project=cls.a, name="Alpha catalog only", created_by=cls.users[Role.ADMIN])
        cls.foreign_test = TestDefinition.objects.create(project=cls.b, name="Secret Beta test", created_by=cls.foreign_user)
        for role in [Role.ENGINEER, Role.OPERATOR, Role.VIEWER]:
            DeviceGrant.objects.create(membership=cls.members[role], device=cls.device)
            TestGrant.objects.create(membership=cls.members[role], test=cls.test)

    def sign_in(self, role=Role.VIEWER):
        self.client.force_login(self.users[role])

    def url(self, section="overview", project=None):
        return reverse("section", args=[(project or self.a).pk, section])

    def test_anonymous_requires_login(self):
        self.assertEqual(self.client.get(self.url()).status_code, 302)

    def test_real_login_and_logout_flow(self):
        response = self.client.post(reverse("login"), {"username": "VIEWER@EXAMPLE.TEST", "password": PASSWORD})
        self.assertRedirects(response, "/", fetch_redirect_response=False)
        self.assertEqual(self.client.get(self.url()).status_code, 200)
        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)
        self.assertEqual(self.client.post(reverse("logout")).status_code, 302)
        self.assertEqual(self.client.get(self.url()).status_code, 302)
        self.assertEqual(AuditEvent.objects.filter(action__in=["session.login", "session.logout"]).count(), 2)

    def test_invalid_and_inactive_login_are_generic(self):
        responses = []
        self.users[Role.VIEWER].is_active = False
        self.users[Role.VIEWER].save()
        for email in ["unknown@example.test", "viewer@example.test"]:
            response = self.client.post(reverse("login"), {"username": email, "password": PASSWORD})
            self.assertContains(response, "Unable to sign in with those credentials.")
            responses.append(response.context["form"].non_field_errors())
        self.assertEqual(responses[0], responses[1])

    def test_inactive_account_loses_existing_session(self):
        self.sign_in()
        User.objects.filter(pk=self.users[Role.VIEWER].pk).update(is_active=False)
        self.assertEqual(self.client.get(self.url()).status_code, 302)

    def test_all_four_dashboards_and_empty_sections(self):
        for role in Role.values:
            with self.subTest(role=role):
                self.sign_in(role)
                for section in ["overview", "devices", "catalog", "runs", "results"]:
                    response = self.client.get(self.url(section))
                    self.assertEqual(response.status_code, 200)
                    self.assertContains(response, Role(role).label)
                self.assertContains(self.client.get(self.url("runs")), "No runs yet")

    def test_role_appropriate_navigation(self):
        for role in [Role.ENGINEER, Role.OPERATOR, Role.VIEWER]:
            self.sign_in(role)
            response = self.client.get(self.url())
            self.assertNotContains(response, "Users &amp; Roles")
            self.assertNotContains(response, "Audit Log")
        self.sign_in(Role.ADMIN)
        self.assertContains(self.client.get(self.url()), "Users &amp; Roles")

    def test_viewer_cannot_submit_or_edit(self):
        self.sign_in()
        self.assertEqual(self.client.post(reverse("submit_run", args=[self.a.pk])).status_code, 403)
        original_count = AuditEvent.objects.count()
        for name, args, data in [
            ("create_invite", [self.a.pk], {"email": "new@example.test", "role": "admin"}),
            ("change_member", [self.a.pk, self.members[Role.OPERATOR].pk], {"role": "admin", "active": "on"}),
            ("change_grant", [self.a.pk, self.members[Role.VIEWER].pk], {"kind": "device", "record": self.hidden_device.pk, "granted": "on"}),
        ]:
            self.assertEqual(self.client.post(reverse(name, args=args), data).status_code, 404)
        self.assertEqual(AuditEvent.objects.count(), original_count)
        self.members[Role.OPERATOR].refresh_from_db()
        self.assertEqual(self.members[Role.OPERATOR].role, Role.OPERATOR)

    def test_engineer_operator_cannot_manage_access(self):
        for role in [Role.ENGINEER, Role.OPERATOR]:
            self.sign_in(role)
            self.assertEqual(self.client.get(self.url("users")).status_code, 404)
            self.assertEqual(self.client.get(self.url("audit")).status_code, 404)
            self.assertEqual(self.client.post(reverse("create_invite", args=[self.a.pk]), {"email": "x@example.test", "role": "admin"}).status_code, 404)

    def test_cross_project_enumeration_all_project_roles(self):
        for role in Role.values:
            self.sign_in(role)
            self.assertEqual(self.client.get(self.url(project=self.b)).status_code, 404)
            self.assertEqual(self.client.post(reverse("submit_run", args=[self.b.pk])).status_code, 404)
            self.assertNotContains(self.client.get(self.url()), "Secret Beta")
            for kind, obj in [("device", self.foreign_device), ("test", self.foreign_test)]:
                self.assertEqual(self.client.get(reverse("detail", args=[self.a.pk, kind, obj.pk])).status_code, 404)

    def test_ungranted_records_hidden_and_direct_access_denied(self):
        for role in [Role.ENGINEER, Role.OPERATOR, Role.VIEWER]:
            self.sign_in(role)
            response = self.client.get(self.url("devices"))
            self.assertContains(response, self.device.name)
            self.assertNotContains(response, self.hidden_device.name)
            self.assertEqual(self.client.get(reverse("detail", args=[self.a.pk, "device", self.hidden_device.pk])).status_code, 404)
            self.assertEqual(self.client.get(reverse("detail", args=[self.a.pk, "test", self.test.pk])).status_code, 200)

    def test_membership_revocation_immediate(self):
        self.sign_in()
        Membership.objects.filter(pk=self.members[Role.VIEWER].pk).update(active=False)
        self.assertEqual(self.client.get(self.url()).status_code, 404)
        self.assertContains(self.client.get("/", follow=True), "No project access")

    def test_grant_revocation_immediate(self):
        self.sign_in()
        DeviceGrant.objects.filter(membership=self.members[Role.VIEWER]).delete()
        TestGrant.objects.filter(membership=self.members[Role.VIEWER]).delete()
        for kind, obj in [("device", self.device), ("test", self.test)]:
            self.assertEqual(self.client.get(reverse("detail", args=[self.a.pk, kind, obj.pk])).status_code, 404)

    def test_platform_admin_can_access_both_projects(self):
        self.client.force_login(self.platform)
        self.assertEqual(self.client.get(self.url(project=self.b)).status_code, 200)
        self.assertEqual(self.client.get(self.url()).status_code, 200)

    def test_project_admin_is_not_platform_admin(self):
        self.sign_in(Role.ADMIN)
        self.client.post(reverse("change_member", args=[self.a.pk, self.members[Role.OPERATOR].pk]), {"role": "admin", "active": "on", "is_superuser": "on", "is_staff": "on"})
        self.users[Role.OPERATOR].refresh_from_db()
        self.assertFalse(self.users[Role.OPERATOR].is_superuser)
        self.assertFalse(self.users[Role.OPERATOR].is_staff)

    def test_admin_membership_mutation_is_audited(self):
        self.sign_in(Role.ADMIN)
        response = self.client.post(reverse("change_member", args=[self.a.pk, self.members[Role.OPERATOR].pk]), {"role": "viewer"})
        self.assertEqual(response.status_code, 302)
        self.members[Role.OPERATOR].refresh_from_db()
        self.assertFalse(self.members[Role.OPERATOR].active)
        self.assertEqual(self.members[Role.OPERATOR].role, Role.VIEWER)
        self.assertTrue(AuditEvent.objects.filter(action="membership.changed", actor=self.users[Role.ADMIN], project=self.a).exists())

    def test_admin_cannot_mutate_foreign_membership_or_resource(self):
        self.sign_in(Role.ADMIN)
        self.assertEqual(self.client.post(reverse("change_member", args=[self.a.pk, self.foreign_member.pk]), {"role": "viewer"}).status_code, 404)
        self.assertEqual(self.client.post(reverse("change_grant", args=[self.a.pk, self.members[Role.VIEWER].pk]), {"kind": "device", "record": self.foreign_device.pk, "granted": "on"}).status_code, 404)

    def test_grant_mutations_and_audit(self):
        self.sign_in(Role.ADMIN)
        endpoint = reverse("change_grant", args=[self.a.pk, self.members[Role.VIEWER].pk])
        payload = {"kind": "device", "record": self.hidden_device.pk, "granted": "on"}
        self.assertEqual(self.client.post(endpoint, payload).status_code, 302)
        self.assertTrue(DeviceGrant.objects.filter(membership=self.members[Role.VIEWER], device=self.hidden_device).exists())
        payload.pop("granted")
        self.client.post(endpoint, payload)
        self.assertFalse(DeviceGrant.objects.filter(membership=self.members[Role.VIEWER], device=self.hidden_device).exists())
        self.assertEqual(AuditEvent.objects.filter(action="grant.changed").count(), 2)

    def test_invalid_roles_and_payloads_rejected(self):
        self.sign_in(Role.ADMIN)
        self.assertEqual(self.client.post(reverse("change_member", args=[self.a.pk, self.members[Role.VIEWER].pk]), {"role": "superuser"}).status_code, 400)
        self.assertEqual(self.client.post(reverse("create_invite", args=[self.a.pk]), {"email": "new@example.test", "role": "superuser"}).status_code, 400)
        self.assertEqual(self.client.post(reverse("change_grant", args=[self.a.pk, self.members[Role.VIEWER].pk]), {"kind": "device", "record": "not-a-uuid"}).status_code, 400)

    def test_cannot_change_own_membership(self):
        self.sign_in(Role.ADMIN)
        self.assertEqual(self.client.post(reverse("change_member", args=[self.a.pk, self.members[Role.ADMIN].pk]), {"role": "viewer"}).status_code, 400)

    def test_csrf_login_and_mutation(self):
        browser = Client(enforce_csrf_checks=True)
        self.assertEqual(browser.post(reverse("login"), {"username": "viewer@example.test", "password": PASSWORD}).status_code, 403)
        browser.get(reverse("login"))
        csrf = browser.cookies["csrftoken"].value
        self.assertEqual(browser.post(reverse("login"), {"username": "admin@example.test", "password": PASSWORD, "csrfmiddlewaretoken": csrf}).status_code, 302)
        endpoint = reverse("change_member", args=[self.a.pk, self.members[Role.VIEWER].pk])
        self.assertEqual(browser.post(endpoint, {"role": "operator", "active": "on"}).status_code, 403)
        csrf = browser.cookies["csrftoken"].value
        self.assertEqual(browser.post(endpoint, {"role": "operator", "active": "on", "csrfmiddlewaretoken": csrf}).status_code, 302)

    def test_login_throttle_blocks_even_correct_password(self):
        for _ in range(5):
            self.assertEqual(self.client.post(reverse("login"), {"username": "viewer@example.test", "password": "incorrect"}).status_code, 200)
        response = self.client.post(reverse("login"), {"username": "viewer@example.test", "password": PASSWORD})
        self.assertEqual(response.status_code, 429)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_login_throttle_window_expires(self):
        from .models import LoginBucket
        for _ in range(6):
            self.client.post(reverse("login"), {"username": "viewer@example.test", "password": "incorrect"})
        LoginBucket.objects.update(started_at=timezone.now() - timedelta(minutes=11))
        self.assertEqual(self.client.post(reverse("login"), {"username": "viewer@example.test", "password": PASSWORD}).status_code, 302)

    def test_ip_throttle_and_forwarded_header_not_trusted(self):
        for index in range(30):
            self.client.post(reverse("login"), {"username": f"missing{index}@example.test", "password": "bad"}, HTTP_X_FORWARDED_FOR=f"192.0.2.{index}")
        self.assertEqual(self.client.post(reverse("login"), {"username": "operator@example.test", "password": PASSWORD}, HTTP_X_FORWARDED_FOR="203.0.113.2").status_code, 429)

    def test_invitation_http_accept_single_use_and_no_escalation(self):
        self.sign_in(Role.ADMIN)
        response = self.client.post(reverse("create_invite", args=[self.a.pk]), {"email": "new@example.test", "role": "operator", "is_superuser": "on"})
        self.assertEqual(response.status_code, 200)
        token = response.context["token"]
        self.assertEqual(response["Cache-Control"], "no-store, private")
        self.assertEqual(Invitation.objects.get(email="new@example.test").token_hash, digest(token))
        self.client.logout()
        payload = {"token": token, "password": PASSWORD, "confirm_password": PASSWORD, "role": "admin", "is_superuser": "on"}
        self.assertEqual(self.client.post(reverse("accept"), payload).status_code, 302)
        new_user = User.objects.get(email="new@example.test")
        self.assertFalse(new_user.is_superuser)
        self.assertEqual(Membership.objects.get(user=new_user).role, Role.OPERATOR)
        self.assertContains(self.client.post(reverse("accept"), payload), "Invitation unavailable")
        self.assertEqual(User.objects.filter(email="new@example.test").count(), 1)
        self.assertTrue(AuditEvent.objects.filter(action="invitation.accepted").exists())

    def test_expired_invitation_and_weak_password_rejected(self):
        token = invite(self.users[Role.ADMIN], self.a, "weak@example.test", Role.VIEWER)
        payload = {"token": token, "password": "123", "confirm_password": "123"}
        self.assertContains(self.client.post(reverse("accept"), payload), "too short")
        self.assertFalse(User.objects.filter(email="weak@example.test").exists())
        Invitation.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        payload.update(password=PASSWORD, confirm_password=PASSWORD)
        self.assertContains(self.client.post(reverse("accept"), payload), "Invitation unavailable")

    def test_revoked_inviter_invalidates_pending_invite(self):
        token = invite(self.users[Role.ADMIN], self.a, "revoked@example.test", Role.VIEWER)
        Membership.objects.filter(pk=self.members[Role.ADMIN].pk).update(active=False)
        self.assertContains(self.client.post(reverse("accept"), {"token": token, "password": PASSWORD, "confirm_password": PASSWORD}), "Invitation unavailable")
        self.assertFalse(User.objects.filter(email="revoked@example.test").exists())

    def test_invite_existing_account_cannot_reset_password(self):
        self.sign_in(Role.ADMIN)
        self.assertEqual(self.client.post(reverse("create_invite", args=[self.a.pk]), {"email": "viewer@example.test", "role": "admin"}).status_code, 400)
        self.assertFalse(Invitation.objects.exists())

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_recovery_is_generic_and_does_not_email_inactive(self):
        response = self.client.post(reverse("password_reset"), {"email": "viewer@example.test"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        other = self.client.post(reverse("password_reset"), {"email": "absent@example.test"})
        self.assertEqual(response.url, other.url)
        User.objects.filter(pk=self.users[Role.VIEWER].pk).update(is_active=False)
        self.client.post(reverse("password_reset"), {"email": "viewer@example.test"})
        self.assertEqual(len(mail.outbox), 1)

    def test_password_recovery_single_use_and_session_revocation(self):
        user = self.users[Role.VIEWER]
        old_session = Client()
        old_session.force_login(user)
        token = default_token_generator.make_token(user)
        url = reverse("password_reset_confirm", args=[urlsafe_base64_encode(force_bytes(user.pk)), token])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertNotIn(token, response.url)
        self.assertEqual(self.client.post(response.url, {"new_password1": "New-test-only-Meteor!6581", "new_password2": "New-test-only-Meteor!6581"}).status_code, 302)
        self.assertEqual(old_session.get(self.url()).status_code, 302)
        user.refresh_from_db()
        self.assertFalse(default_token_generator.check_token(user, token))
        self.assertTrue(AuditEvent.objects.filter(action="account.password_recovered", actor=user).exists())

    def test_audit_is_read_only_and_project_scoped(self):
        AuditEvent.objects.create(project=self.b, actor=self.foreign_user, action="foreign.secret")
        self.sign_in(Role.ADMIN)
        self.assertNotContains(self.client.get(self.url("audit")), "foreign.secret")
        self.assertEqual(self.client.post(self.url("audit"), {"action": "overwrite"}).status_code, 405)

    def test_catalog_never_claims_execution_or_connection(self):
        self.sign_in(Role.ADMIN)
        self.assertContains(self.client.get(self.url("devices")), "Not registered")
        self.assertContains(self.client.get(self.url("catalog")), "Not executable")
        for role in [Role.ADMIN, Role.ENGINEER, Role.OPERATOR]:
            self.sign_in(role)
            self.assertEqual(self.client.post(reverse("submit_run", args=[self.a.pk])).status_code, 409)

    def test_no_shared_cache_or_referrer_and_http_only_session(self):
        self.client.post(reverse("login"), {"username": "viewer@example.test", "password": PASSWORD})
        response = self.client.get(self.url())
        self.assertEqual(response["Cache-Control"], "no-store, private")
        self.assertEqual(response["Referrer-Policy"], "same-origin")
        self.assertEqual(response["X-Frame-Options"], "DENY")
        self.assertTrue(self.client.cookies["sessionid"]["httponly"])

    def test_browser_login_origin_and_csrf_protection(self):
        browser = Client(enforce_csrf_checks=True)
        page = browser.get(reverse("login"))
        self.assertEqual(page["Referrer-Policy"], "same-origin")
        token = browser.cookies["csrftoken"].value
        data = {"username": "viewer@example.test", "password": PASSWORD, "csrfmiddlewaretoken": token}
        for origin in ("null", "https://attacker.invalid"):
            self.assertEqual(browser.post(reverse("login"), data, HTTP_ORIGIN=origin).status_code, 403)
        self.assertEqual(browser.post(reverse("login"), {"username": data["username"], "password": PASSWORD},
                                      HTTP_ORIGIN="http://testserver").status_code, 403)
        response = browser.post(reverse("login"), data, HTTP_ORIGIN="http://testserver")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(int(browser.session["_auth_user_id"]), self.users[Role.VIEWER].pk)

    def test_recovery_tokens_redacted_from_dev_access_log(self):
        record = logging.LogRecord("django.server", logging.INFO, "", 1, '"GET %s HTTP/1.1" 302', ("/recovery/abc/secret-token/",), None)
        RedactRecoveryFilter().filter(record)
        self.assertNotIn("secret-token", record.getMessage())

    def test_external_next_redirect_is_rejected(self):
        response = self.client.post(reverse("login") + "?next=https://attacker.invalid/", {"username": "viewer@example.test", "password": PASSWORD})
        self.assertEqual(response.url, "/")

    def test_invitation_form_requires_csrf(self):
        browser = Client(enforce_csrf_checks=True)
        token = invite(self.users[Role.ADMIN], self.a, "csrf@example.test", Role.VIEWER)
        self.assertEqual(browser.post(reverse("accept"), {"token": token, "password": PASSWORD, "confirm_password": PASSWORD}).status_code, 403)
        self.assertFalse(User.objects.filter(email="csrf@example.test").exists())

    def test_recovery_token_expiry(self):
        user = self.users[Role.VIEWER]
        token = default_token_generator.make_token(user)
        with override_settings(PASSWORD_RESET_TIMEOUT=-1):
            self.assertFalse(default_token_generator.check_token(user, token))

    def test_null_origin_login_is_denied(self):
        browser = Client(enforce_csrf_checks=True)
        browser.get(reverse("login"))
        csrf = browser.cookies["csrftoken"].value
        response = browser.post(reverse("login"), {"username": "viewer@example.test", "password": PASSWORD, "csrfmiddlewaretoken": csrf}, HTTP_ORIGIN="null")
        self.assertEqual(response.status_code, 403)
        self.assertNotIn("_auth_user_id", browser.session)


class BootstrapTests(TestCase):
    def test_bootstrap_is_interactive_validated_audited_and_single_use(self):
        with patch("builtins.input", side_effect=["owner@example.test", "Local lab"]), patch("lab.management.commands.bootstrap_lab.getpass", side_effect=[PASSWORD, PASSWORD]):
            call_command("bootstrap_lab", stdout=StringIO())
        self.assertTrue(User.objects.get(email="owner@example.test").is_superuser)
        self.assertTrue(AuditEvent.objects.filter(action="bootstrap.created").exists())
        with self.assertRaises(CommandError):
            call_command("bootstrap_lab")

    def test_bootstrap_rejects_weak_password_without_writes(self):
        with patch("builtins.input", side_effect=["owner@example.test", "Local lab"]), patch("lab.management.commands.bootstrap_lab.getpass", side_effect=["123", "123"]), self.assertRaises(CommandError):
            call_command("bootstrap_lab")
        self.assertEqual(User.objects.count(), 0)
