from django.test import TestCase
from django.utils import timezone

from apps.identity.models import User
from apps.reputation.models import Challenge


class ChallengeAdminHttpTests(TestCase):
    def test_admin_can_create_isolated_draft_without_external_target(self):
        admin = User.objects.create_user(
            username="challenge-admin", email="challenge-admin@example.test", password="Complex-Password-731!", platform_role=User.PlatformRole.ADMIN
        )
        self.client.force_login(admin)
        response = self.client.post(
            "/console/challenges/",
            {
                "action": "create",
                "code": "sandbox-admin",
                "title": "Challenge sandbox",
                "scenario": "Scénario fictif entièrement isolé.",
                "rules_version": "v1",
                "rules_hash": "abc123",
                "starts_at": (timezone.now() + timezone.timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S"),
                "ends_at": (timezone.now() + timezone.timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S"),
            },
        )
        self.assertRedirects(response, "/console/challenges/")
        challenge = Challenge.objects.get(code="sandbox-admin")
        self.assertTrue(challenge.is_isolated)
        self.assertFalse(challenge.contains_external_target)
