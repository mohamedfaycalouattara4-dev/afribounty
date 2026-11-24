from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from apps.identity.models import User, UserSession
from apps.integrations.models import ApiKey
from apps.organizations.models import Organization, OrganizationMembership


class PrivilegeReviewCommandTests(TestCase):
    def test_review_reports_sensitive_roles_and_strictly_rejects_expired_active_credentials(self):
        user = User.objects.create_user(
            username="privilege-review",
            email="privilege-review@example.test",
            password="Complex-Password-731!",
            platform_role=User.PlatformRole.ADMIN,
        )
        organization = Organization.objects.create(name="Organisation Privilèges")
        OrganizationMembership.objects.create(organization=organization, user=user, role=OrganizationMembership.Role.OWNER)
        UserSession.objects.create(
            user=user,
            session_key_hash="a" * 64,
            device_label="Session expirée de test",
            expires_at=timezone.now() - timedelta(minutes=1),
        )
        ApiKey.objects.create(
            owner=user,
            label="Clé expirée de test",
            key_prefix="abk_test_expired",
            secret_hash="b" * 64,
            scopes=["programs.read"],
            expires_at=timezone.now() - timedelta(minutes=1),
        )

        output = StringIO()
        call_command("review_privileges", stdout=output)
        report = output.getvalue()
        self.assertIn('"expired_unrevoked_api_keys": 1', report)
        self.assertIn('"expired_unrevoked_user_sessions": 1', report)
        self.assertIn('"admin": 1', report)
        self.assertIn('"owner": 1', report)
        with self.assertRaises(CommandError):
            call_command("review_privileges", strict=True)
