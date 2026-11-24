from django.test import TestCase

from apps.security.audit import audit_integrity_report, record_audit
from apps.security.models import AuditEvent


class AuditIntegrityReportTests(TestCase):
    def test_report_detects_low_level_tampering_without_repairing_event(self):
        event = record_audit(action="security.local_check", resource_type="security", resource_reference="audit-integrity-test")
        self.assertEqual(audit_integrity_report(), {"checked_count": 1, "invalid_count": 0, "valid": True})
        AuditEvent.objects.filter(pk=event.pk).update(metadata={"tampered": True})
        self.assertEqual(audit_integrity_report(), {"checked_count": 1, "invalid_count": 1, "valid": False})
        event.refresh_from_db()
        self.assertEqual(event.metadata, {"tampered": True})
