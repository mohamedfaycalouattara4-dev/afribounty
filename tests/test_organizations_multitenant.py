from django.core.exceptions import PermissionDenied
from django.test import TestCase

from apps.identity.models import User
from apps.organizations.models import ConflictDeclaration, Organization, OrganizationMembership, SecurityContact
from apps.organizations.services import (
    delegate_membership,
    export_organization_data,
    record_organization_change,
    require_organization_permission,
    set_verification_status,
    visible_security_contacts,
)


class MultiTenantOrganizationTests(TestCase):
    def setUp(self):
        self.owner_a = User.objects.create_user(username="owner-a", email="owner-a@example.test", password="Complex-Password-731!")
        self.viewer_b = User.objects.create_user(username="viewer-b", email="viewer-b@example.test", password="Complex-Password-731!")
        self.org_a = Organization.objects.create(name="Organisation A")
        self.org_b = Organization.objects.create(name="Organisation B")
        OrganizationMembership.objects.create(organization=self.org_a, user=self.owner_a, role=OrganizationMembership.Role.OWNER)
        OrganizationMembership.objects.create(organization=self.org_b, user=self.viewer_b, role=OrganizationMembership.Role.VIEWER)

    def test_cross_organization_object_access_is_refused(self):
        with self.assertRaises(PermissionDenied):
            require_organization_permission(user=self.viewer_b, organization=self.org_a, permission="settings.manage")

    def test_owner_can_manage_only_own_organization_and_audit_change(self):
        membership = require_organization_permission(user=self.owner_a, organization=self.org_a, permission="settings.manage")
        self.assertEqual(membership.role, OrganizationMembership.Role.OWNER)
        event = record_organization_change(organization=self.org_a, actor=self.owner_a, action="privacy.updated")
        self.assertEqual(event.organization, self.org_a)

    def test_conflict_of_interest_blocks_even_authorized_member(self):
        ConflictDeclaration.objects.create(organization=self.org_a, user=self.owner_a, reason="Conflit déclaré")
        with self.assertRaises(PermissionDenied):
            require_organization_permission(user=self.owner_a, organization=self.org_a, permission="settings.manage")

    def test_security_contacts_and_privacy_settings_remain_scoped(self):
        contact = SecurityContact.objects.create(organization=self.org_a, label="SOC", email="soc@example.test", emergency=True)
        self.org_a.exports_enabled = True
        self.org_a.privacy_retention_days = 180
        self.org_a.save(update_fields=["exports_enabled", "privacy_retention_days"])
        self.assertEqual(contact.organization_id, self.org_a.id)
        self.assertTrue(self.org_a.exports_enabled)

    def test_owner_can_delegate_and_verify_organization(self):
        delegated = delegate_membership(
            actor=self.owner_a, target_user=self.viewer_b, organization=self.org_a, role=OrganizationMembership.Role.PROGRAM_MANAGER
        )
        verification = set_verification_status(organization=self.org_a, status=Organization.VerificationStatus.VERIFIED, reviewer_reference="reviewer-001")
        self.assertEqual(delegated.role, OrganizationMembership.Role.PROGRAM_MANAGER)
        self.assertEqual(verification.status, Organization.VerificationStatus.VERIFIED)

    def test_export_and_contacts_require_organization_role(self):
        SecurityContact.objects.create(organization=self.org_a, label="SOC", email="soc@example.test", emergency=True)
        self.org_a.exports_enabled = True
        self.org_a.save(update_fields=["exports_enabled"])
        exported = export_organization_data(user=self.owner_a, organization=self.org_a)
        self.assertEqual(exported["organization"]["name"], "Organisation A")
        with self.assertRaises(PermissionDenied):
            export_organization_data(user=self.viewer_b, organization=self.org_a)
        with self.assertRaises(PermissionDenied):
            list(visible_security_contacts(user=self.viewer_b, organization=self.org_a))

    def test_same_organization_viewer_cannot_export_or_delegate(self):
        OrganizationMembership.objects.create(organization=self.org_a, user=self.viewer_b, role=OrganizationMembership.Role.VIEWER)
        self.org_a.exports_enabled = True
        self.org_a.save(update_fields=["exports_enabled"])
        with self.assertRaises(PermissionDenied):
            export_organization_data(user=self.viewer_b, organization=self.org_a)
        with self.assertRaises(PermissionDenied):
            delegate_membership(actor=self.viewer_b, target_user=self.owner_a, organization=self.org_a, role=OrganizationMembership.Role.TRIAGER)

    def test_authorized_program_manager_can_view_security_contacts(self):
        SecurityContact.objects.create(organization=self.org_a, label="SOC", email="soc@example.test", emergency=True)
        OrganizationMembership.objects.create(organization=self.org_a, user=self.viewer_b, role=OrganizationMembership.Role.PROGRAM_MANAGER)
        contacts = list(visible_security_contacts(user=self.viewer_b, organization=self.org_a))
        self.assertEqual(len(contacts), 1)
