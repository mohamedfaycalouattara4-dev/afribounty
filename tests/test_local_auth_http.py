from django.test import TestCase

from apps.identity.local_auth import create_local_account
from apps.identity.models import AccountProfile


class LocalAuthenticationHttpTests(TestCase):
    def test_signup_screen_explains_irrecoverability_and_has_no_email_field(self):
        response = self.client.get("/access/signup/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "sans e-mail ni SMS")
        self.assertContains(response, "affichés une seule fois")
        self.assertNotContains(response, 'name="email"')

    def test_local_signup_creates_session_and_redirects_to_passkey_ceremony(self):
        response = self.client.post(
            "/access/signup/",
            {
                "account_intent": AccountProfile.AccountIntent.RESEARCHER,
                "identifier": "http.chercheur",
                "display_name": "Chercheur HTTP",
                "country_code": "BF",
                "password": "Une-phrase-locale-tres-longue-731!",
                "password_confirmation": "Une-phrase-locale-tres-longue-731!",
                "accepted_rules": "on",
                "acknowledged_recovery": "on",
            },
        )
        self.assertRedirects(response, "/access/passkey/register/")
        self.assertTrue(self.client.session.get("pending_recovery_codes"))
        self.assertContains(self.client.get("/access/passkey/register/"), "Vérifiez avant de continuer", status_code=200)

    def test_login_and_recovery_screens_explicitly_reject_external_channels(self):
        login_response = self.client.get("/access/login/")
        recovery_response = self.client.get("/access/recover/")
        self.assertContains(login_response, "Aucun e-mail, SMS, Google, Facebook")
        self.assertContains(recovery_response, "Aucun e-mail et aucun SMS")

    def test_enrollment_lock_blocks_direct_dashboard_access(self):
        user, _ = create_local_account(
            identifier="http.locked",
            password="Une-phrase-locale-tres-longue-731!",
            consent_version="platform-v2-local-auth",
            account_intent=AccountProfile.AccountIntent.RESEARCHER,
            display_name="Compte verrouillé",
            country_code="BF",
        )
        self.client.force_login(user)
        session = self.client.session
        session["local_enrollment_required"] = True
        session.save()
        response = self.client.get("/dashboard/researcher/")
        self.assertRedirects(response, "/access/passkey/register/", fetch_redirect_response=False)

    def test_login_with_local_password_never_sends_a_message(self):
        user, _ = create_local_account(
            identifier="http.login",
            password="Une-phrase-locale-tres-longue-731!",
            consent_version="platform-v2-local-auth",
            account_intent=AccountProfile.AccountIntent.RESEARCHER,
            display_name="Connexion locale",
            country_code="BF",
        )
        response = self.client.post("/access/login/", {"identifier": user.username, "password": "Une-phrase-locale-tres-longue-731!"})
        self.assertRedirects(response, "/access/passkey/register/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/access/passkey/register/")
