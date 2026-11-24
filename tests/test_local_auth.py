from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.identity.local_auth import (
    authenticate_local_password,
    consume_recovery_code,
    create_local_account,
    issue_recovery_codes,
    registration_options_for,
)
from apps.identity.models import AccountProfile, LocalAuthChallenge, RecoveryCode


class LocalAuthenticationTests(TestCase):
    def make_user(self, identifier="chercheur.local"):
        user, codes = create_local_account(
            identifier=identifier,
            password="Une-phrase-locale-tres-longue-731!",
            consent_version="platform-v2-local-auth",
            account_intent=AccountProfile.AccountIntent.RESEARCHER,
            display_name="Chercheur local",
            country_code="BF",
        )
        return user, codes

    def test_local_signup_has_no_auth_email_and_never_stores_recovery_code_plaintext(self):
        user, codes = self.make_user()
        self.assertIsNone(user.email)
        self.assertTrue(user.has_usable_password())
        self.assertEqual(RecoveryCode.objects.filter(user=user, consumed_at__isnull=True).count(), 10)
        for code in codes:
            self.assertNotIn(code.replace("-", ""), RecoveryCode.objects.values_list("code_hash", flat=True))

    def test_recovery_code_is_single_use_and_revokes_all_managed_sessions(self):
        user, codes = self.make_user("recovery.local")
        user.managed_sessions.create(
            session_key_hash="a" * 64,
            device_label="Navigateur local",
            expires_at=timezone.now() + timedelta(days=1),
        )
        consume_recovery_code(user=user, code=codes[0])
        self.assertEqual(user.managed_sessions.filter(revoked_at__isnull=True).count(), 0)
        with self.assertRaises(PermissionDenied):
            consume_recovery_code(user=user, code=codes[0])

    def test_local_password_authentication_is_case_normalized_and_rate_limited(self):
        user, _ = self.make_user("Case.Local")
        self.assertEqual(authenticate_local_password(identifier="case.local", password="Une-phrase-locale-tres-longue-731!"), user)
        for _ in range(5):
            with self.assertRaises(PermissionDenied):
                authenticate_local_password(identifier="case.local", password="mauvais")
        with self.assertRaises(PermissionDenied):
            authenticate_local_password(identifier="case.local", password="Une-phrase-locale-tres-longue-731!")

    @override_settings(AUTH_RP_ID="localhost", AUTH_ORIGIN="http://localhost:8000")
    def test_registration_options_create_short_lived_server_side_challenge(self):
        user, _ = self.make_user("passkey.local")
        request = self.client.get("/access/signup/").wsgi_request
        request.user = user
        options = registration_options_for(user=user, request=request)
        self.assertEqual(options["rp"]["id"], "localhost")
        challenge = LocalAuthChallenge.objects.get(user=user, purpose=LocalAuthChallenge.Purpose.REGISTER)
        self.assertFalse(challenge.consumed_at)
        self.assertGreater(challenge.expires_at, timezone.now())
        self.assertIn("challenge", options)

    def test_issuing_new_recovery_codes_consumes_previous_codes(self):
        user, old_codes = self.make_user("rotate.local")
        new_codes = issue_recovery_codes(user=user)
        self.assertNotEqual(old_codes[0], new_codes[0])
        with self.assertRaises(PermissionDenied):
            consume_recovery_code(user=user, code=old_codes[0])

    def test_invalid_local_identifier_is_rejected_before_database_lookup(self):
        with self.assertRaises(ValidationError):
            authenticate_local_password(identifier="not an identifier", password="anything")
