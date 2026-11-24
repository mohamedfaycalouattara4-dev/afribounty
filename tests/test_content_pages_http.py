from django.test import TestCase

from apps.identity.models import User
from apps.integrations.models import ContentPage


class ContentPagesHttpTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="content-admin", email="content-admin@example.test", password="Complex-Password-731!", platform_role=User.PlatformRole.ADMIN
        )

    def test_default_trust_page_is_public_and_admin_can_publish_local_override(self):
        response = self.client.get("/pages/faq/")
        self.assertContains(response, "FAQ")
        self.client.force_login(self.admin)
        response = self.client.post("/console/content/", {"slug": "faq", "title": "FAQ locale", "body": "Contenu contrôlé", "published": "on"})
        self.assertRedirects(response, "/console/content/")
        self.assertTrue(ContentPage.objects.get(slug="faq").published)
        response = self.client.get("/pages/faq/")
        self.assertContains(response, "FAQ locale")
