from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings

from apps.identity.models import User
from apps.organizations.models import ConflictDeclaration, Organization, OrganizationMembership
from apps.programs.models import Program
from apps.reports.models import Report, ReportConversation, ReportMessage
from apps.reports.services import send_report_message


class ReportConversationTests(TestCase):
    def setUp(self):
        self.researcher = User.objects.create_user(
            username="conversation-researcher",
            email="conversation-researcher@example.test",
            password="Complex-Password-731!",
            platform_role=User.PlatformRole.RESEARCHER,
        )
        self.other_researcher = User.objects.create_user(
            username="conversation-other-researcher",
            email="conversation-other@example.test",
            password="Complex-Password-731!",
            platform_role=User.PlatformRole.RESEARCHER,
        )
        self.owner = User.objects.create_user(
            username="conversation-owner",
            email="conversation-owner@example.test",
            password="Complex-Password-731!",
            platform_role=User.PlatformRole.ORGANIZATION,
        )
        self.viewer = User.objects.create_user(
            username="conversation-viewer",
            email="conversation-viewer@example.test",
            password="Complex-Password-731!",
            platform_role=User.PlatformRole.ORGANIZATION,
        )
        self.triager = User.objects.create_user(
            username="conversation-triager",
            email="conversation-triager@example.test",
            password="Complex-Password-731!",
            platform_role=User.PlatformRole.ORGANIZATION,
        )
        self.organization = Organization.objects.create(name="Organisation conversations", verification_status=Organization.VerificationStatus.VERIFIED)
        OrganizationMembership.objects.create(organization=self.organization, user=self.owner, role=OrganizationMembership.Role.OWNER)
        OrganizationMembership.objects.create(organization=self.organization, user=self.viewer, role=OrganizationMembership.Role.VIEWER)
        OrganizationMembership.objects.create(organization=self.organization, user=self.triager, role=OrganizationMembership.Role.TRIAGER)
        self.program = Program.objects.create(
            organization=self.organization,
            name="Programme conversations",
            status=Program.Status.PUBLIC_ACTIVE,
            policy_version="v1",
            policy_hash="conversation-policy",
        )
        self.report = Report.objects.create(
            organization=self.organization,
            program=self.program,
            author=self.researcher,
            title="Rapport de conversation",
            asset="https://scope.conversation.test",
            impact="Impact fictif",
            reproduction="Étapes fictives",
            policy_version="v1",
            policy_hash="conversation-policy",
            idempotency_key="report-conversation-key-0001",
        )

    def test_authorized_participants_can_send_idempotently_and_message_validation_is_enforced(self):
        first = send_report_message(
            report=self.report,
            actor=self.researcher,
            body="Précision fictive du chercheur.",
            idempotency_key="researcher-message-key-0001",
        )
        second = send_report_message(
            report=self.report,
            actor=self.researcher,
            body="Précision fictive du chercheur.",
            idempotency_key="researcher-message-key-0001",
        )
        organization_message = send_report_message(
            report=self.report,
            actor=self.owner,
            body="Demande fictive de clarification.",
            idempotency_key="owner-message-key-00000001",
        )
        self.assertTrue(first.was_created)
        self.assertFalse(second.was_created)
        self.assertTrue(organization_message.was_created)
        self.assertEqual(ReportConversation.objects.filter(report=self.report).count(), 1)
        self.assertEqual(ReportMessage.objects.filter(conversation__report=self.report).count(), 2)
        with self.assertRaises(ValidationError):
            send_report_message(report=self.report, actor=self.researcher, body="   ", idempotency_key="empty-message-key-00000001")
        with self.assertRaises(ValidationError):
            send_report_message(report=self.report, actor=self.researcher, body="x" * 4001, idempotency_key="long-message-key-000000001")

    def test_http_hides_the_conversation_from_third_parties_and_conflicted_members(self):
        researcher_url = f"/reports/{self.report.id}/"
        researcher_post_url = f"/reports/{self.report.id}/conversation/messages/"
        organization_url = f"/organization/{self.organization.id}/reports/{self.report.id}/"
        organization_post_url = f"/organization/{self.organization.id}/reports/{self.report.id}/conversation/messages/"

        self.client.force_login(self.researcher)
        posted = self.client.post(researcher_post_url, {"body": "Message chercheur fictif.", "message_key": "researcher-http-message-key-01"})
        self.assertRedirects(posted, researcher_url)
        self.assertContains(self.client.get(researcher_url), "Message chercheur fictif.")

        self.client.force_login(self.owner)
        self.assertContains(self.client.get(organization_url), "Message chercheur fictif.")
        posted = self.client.post(organization_post_url, {"body": "Réponse organisation fictive.", "message_key": "owner-http-message-key-000001"})
        self.assertRedirects(posted, organization_url)
        self.assertContains(self.client.get(organization_url), "Réponse organisation fictive.")

        self.client.force_login(self.other_researcher)
        self.assertEqual(self.client.get(researcher_url).status_code, 404)
        self.assertEqual(self.client.post(researcher_post_url, {"body": "Interdit", "message_key": "other-message-key-000000001"}).status_code, 404)

        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(organization_url).status_code, 404)

        ConflictDeclaration.objects.create(organization=self.organization, user=self.triager, reason="Conflit de test", active=True)
        self.client.force_login(self.triager)
        self.assertEqual(self.client.get(organization_url).status_code, 404)

    @override_settings(DEBUG=True)
    def test_private_report_404_is_non_technical_for_a_third_researcher(self):
        self.client.force_login(self.other_researcher)
        response = self.client.get(f"/reports/{self.report.id}/")
        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "Ressource indisponible", status_code=404)
        self.assertNotContains(response, "No Report matches", status_code=404)
