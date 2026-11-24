from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.identity.models import AuthenticationEvent, RecoveryRequest, User
from apps.identity.services import (
    _totp_code,
    approve_recovery,
    authenticate_password,
    consume_recovery,
    create_managed_session,
    enroll_totp,
    grant_step_up,
    has_platform_permission,
    register_user,
    request_recovery,
    require_step_up,
    revoke_session,
    revoke_totp,
    verify_email,
    verify_totp,
)


class IdentityFlowTests(TestCase):
    def test_registration_email_verification_and_consent(self):
        user, token = register_user(email="researcher@example.test", password="Complex-Password-731!", consent_version="v1")
        self.assertFalse(user.email_verified)
        verified = verify_email(token=token)
        self.assertTrue(verified.email_verified)
        self.assertEqual(verified.consents.count(), 1)

    def test_repeated_bad_password_is_blocked_then_valid_password_remains_refused_during_window(self):
        user, _ = register_user(email="lock@example.test", password="Complex-Password-731!", consent_version="v1")
        for _ in range(5):
            with self.assertRaises(PermissionDenied):
                authenticate_password(email=user.email, password="wrong-password")
        with self.assertRaises(PermissionDenied):
            authenticate_password(email=user.email, password="Complex-Password-731!")
        self.assertEqual(AuthenticationEvent.objects.filter(event_type="identity.login_blocked").count(), 1)

    def test_totp_replay_is_refused_and_revocation_blocks_future_use(self):
        user, _ = register_user(email="totp@example.test", password="Complex-Password-731!", consent_version="v1")
        device = enroll_totp(user=user, secret="JBSWY3DPEHPK3PXP", label="Test device")
        now = timezone.now().replace(microsecond=0)
        code = _totp_code("JBSWY3DPEHPK3PXP", int(now.timestamp()) // 30)
        self.assertTrue(verify_totp(device=device, code=code, at_time=now))
        self.assertFalse(verify_totp(device=device, code=code, at_time=now))
        revoke_totp(device=device)
        self.assertFalse(verify_totp(device=device, code=code, at_time=now + timedelta(seconds=30)))

    def test_session_recovery_roles_and_step_up(self):
        user, _ = register_user(email="admin@example.test", password="Complex-Password-731!", consent_version="v1")
        user.platform_role = User.PlatformRole.ADMIN
        user.save(update_fields=["platform_role"])
        session = create_managed_session(user=user, raw_session_key="synthetic-session-key", device_label="Test browser")
        revoke_session(session=session)
        session.refresh_from_db()
        self.assertIsNotNone(session.revoked_at)
        recovery_token = request_recovery(user=user)
        recovery = RecoveryRequest.objects.get(user=user)
        approve_recovery(request=recovery, reviewer_reference="security-reviewer-001")
        self.assertEqual(consume_recovery(token=recovery_token), user)
        with self.assertRaises(ValidationError):
            consume_recovery(token=recovery_token)
        self.assertTrue(has_platform_permission(user=user, permission="reward.approve"))
        with self.assertRaises(PermissionDenied):
            require_step_up(user=user, action="beneficiary.change")
        grant_step_up(user=user, action="beneficiary.change")
        require_step_up(user=user, action="beneficiary.change")

    def test_authentication_event_is_append_only(self):
        user, _ = register_user(email="audit@example.test", password="Complex-Password-731!", consent_version="v1")
        event = AuthenticationEvent.objects.filter(user=user).first()
        event.event_type = "tampered"
        with self.assertRaises(ValidationError):
            event.save()
