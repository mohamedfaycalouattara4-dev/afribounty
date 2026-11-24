from django.test import TestCase
from django.utils import timezone

from apps.identity.models import AccountProfile, User
from apps.reputation.models import ReputationProfile, ReputationSeason


class PublicResearcherProfilesHttpTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="public-profile", email="public-profile@example.test", password="Complex-Password-731!", platform_role=User.PlatformRole.RESEARCHER
        )
        AccountProfile.objects.create(user=self.user, display_name="Profil local", country_code="BF", account_intent=AccountProfile.AccountIntent.RESEARCHER)
        self.season = ReputationSeason.objects.create(
            code="active-local", starts_at=timezone.now() - timezone.timedelta(days=1), ends_at=timezone.now() + timezone.timedelta(days=1), active=True
        )
        ReputationProfile.objects.create(user=self.user, season=self.season, points=42, rank=1, recalculated_at=timezone.now())

    def test_public_leaderboard_requires_opt_in_and_only_exposes_alias_and_calculated_metrics(self):
        self.client.force_login(self.user)
        self.client.post("/reputation/public-profile/", {"public_alias": "Awa sécurité", "opted_in": "on"})
        response = self.client.get("/community/researchers/")
        self.assertContains(response, "Awa sécurité")
        self.assertContains(response, "42")
        self.assertNotContains(response, self.user.email)
