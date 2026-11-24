from django.test import TestCase
from django.utils import timezone

from apps.identity.local_auth import create_local_account
from apps.identity.models import AccountProfile, ConsentRecord, User
from apps.organizations.models import OrganizationMembership, OrganizationVerification


class VisibleIdentitySliceTests(TestCase):
    def test_researcher_local_signup_creates_profile_and_recovery_codes(self):
        user, recovery_codes = create_local_account(
            identifier="awa.recherche",
            password="Une-phrase-locale-tres-longue-731!",
            consent_version="platform-v2-local-auth",
            account_intent=AccountProfile.AccountIntent.RESEARCHER,
            display_name="Awa Recherche",
            country_code="BF",
        )
        self.assertTrue(user.email_verified)
        self.assertEqual(user.platform_role, User.PlatformRole.RESEARCHER)
        self.assertEqual(user.account_profile.display_name, "Awa Recherche")
        self.assertTrue(user.has_usable_password())
        self.assertIsNone(user.email)
        self.assertEqual(len(recovery_codes), 10)
        self.assertTrue(ConsentRecord.objects.filter(user=user, policy_code="terms", policy_version="platform-v2-local-auth").exists())

    def test_organization_signup_creates_pending_organization_and_owner_membership(self):
        user, _ = create_local_account(
            identifier="owner.slice",
            password="Une-phrase-locale-tres-longue-731!",
            consent_version="platform-v2-local-auth",
            account_intent=AccountProfile.AccountIntent.ORGANIZATION,
            display_name="Responsable SSI",
            country_code="BF",
            organization_name="Société de démonstration",
        )
        membership = OrganizationMembership.objects.get(user=user)
        self.assertEqual(membership.role, OrganizationMembership.Role.OWNER)
        self.assertEqual(membership.organization.verification_status, "pending")
        self.assertEqual(OrganizationVerification.objects.get(organization=membership.organization).status, "pending")

    def test_public_identity_pages_and_protected_redirection_are_rendered(self):
        signup = self.client.get("/access/signup/")
        self.assertContains(signup, "Chercheur en sécurité")
        self.assertContains(signup, "Organisation")
        protected = self.client.get("/dashboard/researcher/")
        self.assertRedirects(protected, "/access-required/?next=/dashboard/researcher/", fetch_redirect_response=False)
        access_required = self.client.get("/access-required/?next=/dashboard/researcher/")
        self.assertEqual(access_required.status_code, 403)
        self.assertContains(access_required, "Une session utilisateur est requise.", status_code=403)

    def test_authenticated_onboarding_routes_researcher_and_organization_correctly(self):
        researcher = User.objects.create_user(
            username="onboarding-researcher",
            email="onboarding-researcher@example.test",
            password="Not-used-123!",
            email_verified=True,
            platform_role=User.PlatformRole.RESEARCHER,
        )
        AccountProfile.objects.create(
            user=researcher,
            display_name="Chercheur",
            country_code="BF",
            account_intent=AccountProfile.AccountIntent.RESEARCHER,
        )
        self.client.force_login(researcher)
        response = self.client.post("/onboarding/", {"understood": "on"})
        self.assertRedirects(response, "/dashboard/researcher/")
        researcher.account_profile.refresh_from_db()
        self.assertIsNotNone(researcher.account_profile.onboarding_completed_at)

    def test_authenticated_user_is_not_allowed_to_restart_signup(self):
        user = User.objects.create_user(
            username="already-authenticated",
            email="already-authenticated@example.test",
            password="Not-used-123!",
            email_verified=True,
            platform_role=User.PlatformRole.RESEARCHER,
        )
        AccountProfile.objects.create(
            user=user,
            display_name="Compte actif",
            country_code="BF",
            account_intent=AccountProfile.AccountIntent.RESEARCHER,
        )
        self.client.force_login(user)
        response = self.client.get("/access/signup/")
        self.assertRedirects(response, "/dashboard/researcher/")

    def test_local_login_requires_passkey_enrollment_before_dashboard_access(self):
        user, _ = create_local_account(
            identifier="returning.researcher",
            password="Une-phrase-locale-tres-longue-731!",
            consent_version="platform-v2-local-auth",
            account_intent=AccountProfile.AccountIntent.RESEARCHER,
            display_name="Compte déjà onboardé",
            country_code="BF",
        )
        user.account_profile.onboarding_completed_at = timezone.now()
        user.account_profile.save(update_fields=["onboarding_completed_at"])

        response = self.client.post("/access/login/", {"identifier": user.username, "password": "Une-phrase-locale-tres-longue-731!"})

        self.assertRedirects(response, "/access/passkey/register/")
        self.assertEqual(self.client.session.get("_auth_user_id"), str(user.pk))

    def test_legacy_email_login_route_is_explicitly_disabled(self):
        response = self.client.get("/access/verify/obsolete-token/")
        self.assertEqual(response.status_code, 410)
        self.assertContains(response, "liens de connexion et de vérification par e-mail", status_code=410)
