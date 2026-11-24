from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from apps.integrations.external_readiness import external_service_registry_integrity_report


class ExternalServiceRegistryTests(SimpleTestCase):
    def test_registry_is_disabled_and_strict_command_detects_a_local_divergence(self):
        self.assertEqual(external_service_registry_integrity_report(), {"checked_count": 7, "invalid_count": 0, "valid": True})
        output = StringIO()
        call_command("verify_external_service_registry", "--strict", stdout=output)
        self.assertIn('"valid": true', output.getvalue())

        invalid_registry = {
            "transactional_email": {"enabled": True, "provider": "forbidden-provider"},
        }
        with patch("apps.integrations.external_readiness.external_service_readiness", return_value=invalid_registry):
            self.assertEqual(external_service_registry_integrity_report(), {"checked_count": 1, "invalid_count": 1, "valid": False})
            with self.assertRaises(CommandError):
                call_command("verify_external_service_registry", "--strict")
