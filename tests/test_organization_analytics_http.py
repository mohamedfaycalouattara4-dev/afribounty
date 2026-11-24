from django.test import TestCase

from apps.identity.models import User
from apps.organizations.models import Organization, OrganizationMembership
from apps.programs.models import Program
from apps.reports.models import Report


class OrganizationAnalyticsHttpTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="analytics-owner", email="analytics-owner@example.test", password="Complex-Password-731!", platform_role=User.PlatformRole.ORGANIZATION
        )
        self.viewer = User.objects.create_user(
            username="analytics-viewer", email="analytics-viewer@example.test", password="Complex-Password-731!", platform_role=User.PlatformRole.ORGANIZATION
        )
        self.researcher = User.objects.create_user(
            username="analytics-researcher",
            email="analytics-researcher@example.test",
            password="Complex-Password-731!",
            platform_role=User.PlatformRole.RESEARCHER,
        )
        self.organization = Organization.objects.create(name="Organisation analytique", verification_status=Organization.VerificationStatus.VERIFIED)
        OrganizationMembership.objects.create(organization=self.organization, user=self.owner, role=OrganizationMembership.Role.OWNER)
        OrganizationMembership.objects.create(organization=self.organization, user=self.viewer, role=OrganizationMembership.Role.VIEWER)
        program = Program.objects.create(
            organization=self.organization,
            name="Programme analytique",
            status=Program.Status.PUBLIC_ACTIVE,
            policy_version="v1",
            policy_hash="analytics-policy",
        )
        Report.objects.create(
            organization=self.organization,
            program=program,
            author=self.researcher,
            title="Rapport analytique",
            asset="https://analytics.example.test",
            impact="Impact fictif",
            reproduction="Étapes fictives",
            policy_version="v1",
            policy_hash="analytics-policy",
            idempotency_key="analytics-report-key-0001",
        )

    def test_owner_sees_aggregates_and_viewer_is_refused(self):
        url = f"/organization/{self.organization.id}/analytics/"
        self.client.force_login(self.owner)
        self.assertContains(self.client.get(url), "Rapport analytique".replace("Rapport analytique", "Soumis"))
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(url).status_code, 403)
