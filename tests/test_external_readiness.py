from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from apps.integrations.external_readiness import external_service_readiness, require_external_service_activation


class ExternalReadinessTests(SimpleTestCase):
    def test_all_external_services_are_explicitly_prepared_but_disabled(self):
        readiness = external_service_readiness()
        self.assertFalse(readiness["transactional_email"]["enabled"])
        self.assertEqual(readiness["regional_payment"]["provider"], "disabled")
        self.assertIn("contrat", readiness["kyc_verification"]["activation_requires"])
        with self.assertRaises(ImproperlyConfigured):
            require_external_service_activation(service="regional_payment")

    def test_unknown_external_service_is_refused(self):
        with self.assertRaises(ImproperlyConfigured):
            require_external_service_activation(service="unknown")
