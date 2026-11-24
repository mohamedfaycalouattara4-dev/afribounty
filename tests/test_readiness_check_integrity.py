from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from apps.readiness.models import ReadinessCheck
from apps.readiness.services import _digest, readiness_check_integrity_report


class ReadinessCheckIntegrityTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="readiness-integrity", email="readiness.integrity@example.test")

    def test_report_and_strict_command_detect_a_tampered_check_without_repairing_it(self):
        evidence = {"calculated_locally": True, "external_service_called": False}
        readiness_check = ReadinessCheck.objects.create(
            check_code="unit_tests",
            status=ReadinessCheck.Status.PASS,
            evidence={**evidence, "evidence_digest": _digest(evidence)},
            recorded_by=self.user,
        )
        self.assertEqual(readiness_check_integrity_report(), {"checked_count": 1, "invalid_count": 0, "valid": True})
        output = StringIO()
        call_command("verify_readiness_check_integrity", "--strict", stdout=output)
        self.assertIn('"valid": true', output.getvalue())

        ReadinessCheck.objects.filter(pk=readiness_check.pk).update(
            evidence={"calculated_locally": False, "external_service_called": False, "evidence_digest": readiness_check.evidence["evidence_digest"]}
        )
        self.assertEqual(readiness_check_integrity_report(), {"checked_count": 1, "invalid_count": 1, "valid": False})
        with self.assertRaises(CommandError):
            call_command("verify_readiness_check_integrity", "--strict")
        readiness_check.refresh_from_db()
        self.assertFalse(readiness_check.evidence["calculated_locally"])
