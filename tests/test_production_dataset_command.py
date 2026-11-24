from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from apps.identity.models import User


class ProductionDatasetCommandTests(TestCase):
    def test_strict_check_passes_on_empty_dataset(self):
        output = StringIO()
        call_command("verify_production_dataset", "--strict", stdout=output)
        self.assertIn("aucun artefact", output.getvalue())

    def test_strict_check_refuses_demo_account(self):
        User.objects.create_user(
            username="demo-release-check",
            email="demo-release-check@example.test",
            password="Complex-Password-731!",
            platform_role=User.PlatformRole.RESEARCHER,
        )
        with self.assertRaises(CommandError):
            call_command("verify_production_dataset", "--strict")
