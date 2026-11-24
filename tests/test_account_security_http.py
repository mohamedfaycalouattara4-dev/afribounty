from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.identity.models import ConsentRecord, User, UserSession


class AccountSecurityHttpTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="security-settings", email="security-settings@example.test", password="Complex-Password-731!", platform_role=User.PlatformRole.RESEARCHER
        )
        ConsentRecord.objects.create(user=self.user, policy_code="terms", policy_version="v1", correlation_id="test")
        self.session = UserSession.objects.create(
            user=self.user, session_key_hash="a" * 64, device_label="Navigateur local", expires_at=timezone.now() + timedelta(days=1)
        )

    def test_account_security_view_lists_safe_metadata_and_revokes_owned_session(self):
        self.client.force_login(self.user)
        response = self.client.get("/settings/security/")
        self.assertContains(response, "Navigateur local")
        self.assertNotContains(response, self.session.session_key_hash)
        response = self.client.post("/settings/security/", {"action": "revoke_session", "session_id": self.session.id})
        self.assertRedirects(response, "/settings/security/")
        self.session.refresh_from_db()
        self.assertIsNotNone(self.session.revoked_at)
