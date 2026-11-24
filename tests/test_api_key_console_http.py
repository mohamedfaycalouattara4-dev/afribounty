from django.test import TestCase

from apps.identity.models import User
from apps.identity.services import grant_step_up
from apps.integrations.models import ApiKey


class ApiKeyConsoleHttpTests(TestCase):
    def test_owner_creates_key_and_only_prefix_is_persisted_or_listed(self):
        user = User.objects.create_user(
            username="api-console", email="api-console@example.test", password="Complex-Password-731!", platform_role=User.PlatformRole.RESEARCHER
        )
        grant_step_up(user=user, action="api_key.create")
        self.client.force_login(user)
        response = self.client.post("/settings/developer/keys/", {"action": "create", "label": "test locale", "scopes": "reports.read", "ttl_days": "30"})
        self.assertRedirects(response, "/settings/developer/keys/")
        key = ApiKey.objects.get(owner=user)
        response = self.client.get("/settings/developer/keys/")
        self.assertContains(response, key.key_prefix)
        self.assertNotContains(response, key.secret_hash)
