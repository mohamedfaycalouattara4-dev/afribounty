from django.test import TestCase

from apps.identity.models import User
from apps.integrations.models import SupportCase


class SupportHttpTests(TestCase):
    def setUp(self):
        self.researcher = User.objects.create_user(
            username="support-researcher", email="support-researcher@example.test", password="Complex-Password-731!", platform_role=User.PlatformRole.RESEARCHER
        )
        self.admin = User.objects.create_user(
            username="support-admin", email="support-admin@example.test", password="Complex-Password-731!", platform_role=User.PlatformRole.ADMIN
        )

    def test_researcher_opens_sanitized_ticket_and_admin_replies(self):
        self.client.force_login(self.researcher)
        response = self.client.post("/support/", {"subject": "Question locale", "message": "Comment mettre à jour mon profil ?"})
        self.assertRedirects(response, "/support/")
        case = SupportCase.objects.get(requester=self.researcher)
        self.assertEqual(self.client.post("/support/", {"subject": "Secret", "message": "Voici un token secret."}).status_code, 200)
        self.client.force_login(self.admin)
        response = self.client.post("/console/support/", {"case_id": case.id, "status": "closed", "reply": "Votre demande locale est traitée."})
        self.assertRedirects(response, "/console/support/")
        case.refresh_from_db()
        self.assertEqual(case.status, SupportCase.Status.CLOSED)
        self.assertEqual(case.replies.count(), 1)

    def test_support_console_refuses_researcher(self):
        self.client.force_login(self.researcher)
        self.assertEqual(self.client.get("/console/support/").status_code, 403)
