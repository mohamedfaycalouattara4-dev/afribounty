from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.identity.models import User
from apps.identity.services import grant_step_up
from apps.integrations.models import ApiKeyUsageEvent
from apps.integrations.services import create_api_key
from apps.organizations.models import Organization
from apps.programs.models import AssetScope, Program


class PublicApiV1Tests(TestCase):
    def setUp(self):
        organization = Organization.objects.create(name="Organisation API", verification_status=Organization.VerificationStatus.VERIFIED)
        self.program = Program.objects.create(
            organization=organization,
            name="Programme API public",
            status=Program.Status.PUBLIC_ACTIVE,
            policy_version="v1",
            policy_hash="api-policy",
        )
        AssetScope.objects.create(
            program=self.program,
            asset="https://api.example.test",
            asset_type="web",
            is_active=True,
            is_verified=True,
            is_excluded=False,
        )
        hidden_org = Organization.objects.create(name="Organisation non vérifiée")
        Program.objects.create(
            organization=hidden_org,
            name="Programme privé API",
            status=Program.Status.PUBLIC_ACTIVE,
            policy_version="v1",
            policy_hash="hidden-policy",
        )

    def test_api_lists_only_verified_public_programs_and_schema(self):
        listing = self.client.get("/api/v1/programs/?q=API")
        self.assertEqual(listing.status_code, 200)
        self.assertEqual([item["id"] for item in listing.json()["data"]], [self.program.id])
        schema = self.client.get("/api/v1/openapi.json")
        self.assertEqual(schema.status_code, 200)
        self.assertEqual(schema.json()["openapi"], "3.0.3")

    def test_api_detail_hides_non_public_programs_and_returns_verified_scopes(self):
        detail = self.client.get(f"/api/v1/programs/{self.program.id}/")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["data"]["scopes"][0]["asset"], "https://api.example.test")
        self.assertEqual(self.client.get("/api/v1/programs/99999/").status_code, 404)

    def test_api_key_inspection_requires_authorized_key_and_records_safe_usage(self):
        user = User.objects.create_user(
            username="api-owner", email="api-owner@example.test", password="Complex-Password-731!", platform_role=User.PlatformRole.RESEARCHER
        )
        grant_step_up(user=user, action="api_key.create")
        _, raw_key = create_api_key(owner=user, label="lecture programme", scopes=["programs.read"])
        self.assertEqual(self.client.get("/api/v1/key/").status_code, 401)
        response = self.client.get("/api/v1/key/", HTTP_AUTHORIZATION=f"Bearer {raw_key}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["scopes"], ["programs.read"])
        self.assertEqual(ApiKeyUsageEvent.objects.get().safe_reference, "api:v1:key-inspection")

    def test_api_key_rejects_scope_outside_the_closed_allowlist(self):
        user = User.objects.create_user(
            username="api-scope-refused", email="api-scope-refused@example.test", password="Complex-Password-731!", platform_role=User.PlatformRole.RESEARCHER
        )
        grant_step_up(user=user, action="api_key.create")
        with self.assertRaises(ValidationError):
            create_api_key(owner=user, label="interdit", scopes=["finance.write"])
