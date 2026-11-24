from django.test import TestCase

from apps.identity.models import AccountDataRequest, AccountPrivacyPreference, User


class PrivacyRequestsHttpTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="privacy-requester", email="privacy-requester@example.test", password="Complex-Password-731!", platform_role=User.PlatformRole.RESEARCHER
        )
        AccountPrivacyPreference.objects.create(user=self.user, exports_enabled=True)

    def test_researcher_can_register_and_cancel_local_data_rights_requests(self):
        self.client.force_login(self.user)
        response = self.client.post("/settings/privacy/", {"action": "request_export"})
        self.assertRedirects(response, "/settings/privacy/")
        data_request = AccountDataRequest.objects.get(user=self.user, request_type=AccountDataRequest.RequestType.EXPORT)
        response = self.client.get("/settings/privacy/")
        self.assertContains(response, "Export de données")
        self.assertNotContains(response, "Complex-Password-731!")
        self.client.post("/settings/privacy/", {"action": "cancel_request", "request_id": data_request.id})
        data_request.refresh_from_db()
        self.assertEqual(data_request.state, AccountDataRequest.State.CANCELLED)
