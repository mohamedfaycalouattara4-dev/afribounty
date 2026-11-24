from django.test import TestCase

from apps.organizations.models import Organization
from apps.programs.models import AssetScope, Program


class ProgramCatalogHttpTests(TestCase):
    def setUp(self):
        self.verified = Organization.objects.create(name="Catalogue vérifié", verification_status=Organization.VerificationStatus.VERIFIED)
        self.unverified = Organization.objects.create(name="Catalogue non vérifié", verification_status=Organization.VerificationStatus.PENDING)
        self.public_program = Program.objects.create(
            organization=self.verified, name="API locale publique", status=Program.Status.PUBLIC_ACTIVE, policy_version="v1", policy_hash="catalog-public"
        )
        AssetScope.objects.create(program=self.public_program, asset="https://api.catalog.test", asset_type=AssetScope.AssetType.API, is_verified=True)
        Program.objects.create(
            organization=self.verified, name="Programme privé caché", status=Program.Status.PRIVATE_ACTIVE, policy_version="v1", policy_hash="catalog-private"
        )
        Program.objects.create(
            organization=self.unverified,
            name="Programme non vérifié caché",
            status=Program.Status.PUBLIC_ACTIVE,
            policy_version="v1",
            policy_hash="catalog-pending",
        )

    def test_catalog_only_shows_verified_public_programs_and_filters_by_asset_category(self):
        response = self.client.get("/programs/?q=locale&asset_type=api")
        self.assertContains(response, "API locale publique")
        self.assertNotContains(response, "Programme privé caché")
        self.assertNotContains(response, "Programme non vérifié caché")
