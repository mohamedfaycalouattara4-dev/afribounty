from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from apps.readiness.services import local_integrity_report
from apps.security.audit import record_audit
from apps.security.models import AuditEvent


class LocalIntegrityCommandTests(TestCase):
    def test_strict_command_aggregates_local_checks_and_detects_tampering_without_repair(self):
        self.assertTrue(local_integrity_report()["valid"])
        self.assertTrue(local_integrity_report()["checks"]["external_service_registry"]["valid"])
        event = record_audit(action="security.local_integrity", resource_type="security", resource_reference="consolidated-test")
        call_command("verify_local_integrity", "--strict")
        AuditEvent.objects.filter(pk=event.pk).update(metadata={"tampered": True})
        report = local_integrity_report()
        self.assertFalse(report["valid"])
        self.assertFalse(report["checks"]["audit_hmac"]["valid"])
        with self.assertRaises(CommandError):
            call_command("verify_local_integrity", "--strict")
        event.refresh_from_db()
        self.assertEqual(event.metadata, {"tampered": True})

    def test_strict_command_detects_invalid_external_registry_without_contacting_a_provider(self):
        invalid_registry = {"transactional_email": {"enabled": True, "provider": "not-allowed"}}
        with patch("apps.integrations.external_readiness.external_service_readiness", return_value=invalid_registry):
            report = local_integrity_report()
            self.assertFalse(report["valid"])
            self.assertFalse(report["checks"]["external_service_registry"]["valid"])
            with self.assertRaises(CommandError):
                call_command("verify_local_integrity", "--strict")
