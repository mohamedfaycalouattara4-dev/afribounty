from django.test import TestCase

from apps.identity.models import User
from apps.organizations.models import Organization, OrganizationMembership
from apps.programs.models import Program, ProgramInvitation


class ProgramInvitationHttpTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="invite-owner", email="invite-owner@example.test", password="Complex-Password-731!", platform_role=User.PlatformRole.ORGANIZATION
        )
        self.researcher = User.objects.create_user(
            username="invite-researcher",
            email="invite-researcher@example.test",
            password="Complex-Password-731!",
            platform_role=User.PlatformRole.RESEARCHER,
            email_verified=True,
        )
        self.organization = Organization.objects.create(name="Organisation invitation", verification_status=Organization.VerificationStatus.VERIFIED)
        OrganizationMembership.objects.create(organization=self.organization, user=self.owner, role=OrganizationMembership.Role.OWNER)
        self.program = Program.objects.create(
            organization=self.organization, name="Programme privé", status=Program.Status.PRIVATE_ACTIVE, policy_version="v1", policy_hash="invitation-policy"
        )

    def test_owner_can_create_and_revoke_local_private_invitation(self):
        self.client.force_login(self.owner)
        url = f"/organization/{self.organization.id}/programs/{self.program.id}/invitations/"
        response = self.client.post(url, {"action": "invite", "researcher_email": self.researcher.email})
        self.assertRedirects(response, url)
        invitation = ProgramInvitation.objects.get(program=self.program, researcher=self.researcher)
        response = self.client.get(url)
        self.assertContains(response, self.researcher.email)
        self.client.post(url, {"action": "revoke", "invitation_id": invitation.id})
        invitation.refresh_from_db()
        self.assertIsNotNone(invitation.revoked_at)
