import json
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from apps.identity.models import User
from apps.reports.models import Report
from apps.security.models import AuditEvent


class RestoreExerciseMetricsCommandTests(TestCase):
    def test_command_returns_only_expected_non_sensitive_counters(self):
        User.objects.create_user(
            username="restore-metric-user",
            email="restore-metric-user@example.test",
            password="Complex-Password-731!",
        )
        output = StringIO()

        call_command("restore_exercise_metrics", stdout=output)

        payload = json.loads(output.getvalue())
        self.assertEqual(payload["users"], User.objects.count())
        self.assertEqual(payload["reports"], Report.objects.count())
        self.assertEqual(payload["audit_events"], AuditEvent.objects.count())
        self.assertEqual(
            set(payload),
            {
                "audit_events",
                "database_vendor",
                "evidence_pipeline_states",
                "report_relations",
                "report_sla_escalations",
                "report_sla_states",
                "reports",
                "users",
            },
        )
