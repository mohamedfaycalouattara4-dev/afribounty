from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from apps.identity.models import User
from apps.security.models import PrivilegeReviewSnapshot
from apps.security.privilege_review import privilege_review_snapshot_integrity_report, record_privilege_review_snapshot


class PrivilegeReviewIntegrityTests(TestCase):
    def setUp(self):
        self.security = User.objects.create_user(
            username="integrity-security",
            email="integrity-security@example.test",
            password="Complex-Password-731!",
            email_verified=True,
            platform_role=User.PlatformRole.SECURITY,
        )

    def test_integrity_report_and_strict_command_detect_query_level_tampering_without_repairing(self):
        archived = record_privilege_review_snapshot(actor=self.security, review_reference="integrity-review-001")
        self.assertEqual(privilege_review_snapshot_integrity_report(), {"checked_count": 1, "invalid_count": 0, "valid": True})
        call_command("verify_privilege_review_snapshots", "--strict")
        PrivilegeReviewSnapshot.objects.filter(pk=archived.pk).update(snapshot={"tampered": True})
        self.assertEqual(privilege_review_snapshot_integrity_report(), {"checked_count": 1, "invalid_count": 1, "valid": False})
        with self.assertRaises(CommandError):
            call_command("verify_privilege_review_snapshots", "--strict")
        archived.refresh_from_db()
        self.assertEqual(archived.snapshot, {"tampered": True})
