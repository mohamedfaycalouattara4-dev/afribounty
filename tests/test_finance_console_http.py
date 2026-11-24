from django.test import TestCase

from apps.identity.models import User
from apps.rewards.models import ReconciliationReport


class FinanceConsoleHttpTests(TestCase):
    def test_finance_can_run_empty_local_reconciliation_without_external_provider(self):
        finance = User.objects.create_user(
            username="finance-console", email="finance-console@example.test", password="Complex-Password-731!", platform_role=User.PlatformRole.FINANCE
        )
        self.client.force_login(finance)
        response = self.client.post("/console/finance/", {"action": "reconcile"})
        self.assertRedirects(response, "/console/finance/")
        self.assertEqual(ReconciliationReport.objects.count(), 1)
