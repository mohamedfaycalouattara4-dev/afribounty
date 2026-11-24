from django.test import TestCase

from apps.identity.models import User
from apps.organizations.models import Organization, OrganizationMembership
from apps.organizations.services import record_organization_change


class OrganizationAuditHttpTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="audit-owner", email="audit-owner@example.test", password="Complex-Password-731!", platform_role=User.PlatformRole.ORGANIZATION
        )
        self.viewer = User.objects.create_user(
            username="audit-viewer", email="audit-viewer@example.test", password="Complex-Password-731!", platform_role=User.PlatformRole.ORGANIZATION
        )
        self.organization = Organization.objects.create(name="Organisation audit", verification_status=Organization.VerificationStatus.VERIFIED)
        OrganizationMembership.objects.create(organization=self.organization, user=self.owner, role=OrganizationMembership.Role.OWNER)
        OrganizationMembership.objects.create(organization=self.organization, user=self.viewer, role=OrganizationMembership.Role.VIEWER)
        record_organization_change(
            organization=self.organization, actor=self.owner, action="organization.settings_updated", metadata={"exports_enabled": False}
        )

    def test_only_owner_can_read_organization_audit_log(self):
        url = f"/organization/{self.organization.id}/audit/"
        self.client.force_login(self.owner)
        self.assertContains(self.client.get(url), "organization.settings_updated")
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(url).status_code, 403)
