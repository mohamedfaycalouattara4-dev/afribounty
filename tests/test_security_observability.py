from datetime import timedelta

from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from unittest.mock import patch

from apps.core.correlation import correlation_id
from apps.security.audit import record_audit, verify_audit_event
from apps.security.exceptions import AccountFrozen, ForbiddenNotificationContext
from apps.security.freeze import assert_subject_active, freeze_subject
from apps.security.middleware import SensitiveRateLimitMiddleware
from apps.security.models import AuditEvent, RetentionRecord, SecuritySubject
from apps.security.notifications import render_security_notification
from apps.security.rate_limit import MemoryRateLimiter, RedisRateLimiter, create_rate_limiter
from apps.security.retention import anonymize_expired_records
from apps.security.tasks import retention_anonymization_task


class SandboxProductionGuardTests(TestCase):
    @override_settings(AFRIBOUNTY_ENVIRONMENT="production")
    def test_sandbox_payment_adapter_is_refused_in_production(self):
        from apps.rewards.services import _require_sandbox_environment

        with self.assertRaises(ImproperlyConfigured):
            _require_sandbox_environment()


class HttpSecurityTests(TestCase):
    def test_health_response_has_security_headers_and_correlation(self):
        response = APIClient().get("/health/live/", HTTP_X_CORRELATION_ID="corr-http-security-001")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["X-Correlation-ID"], "corr-http-security-001")
        self.assertIn("default-src 'self'", response["Content-Security-Policy"])
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response["Permissions-Policy"], "geolocation=(), microphone=(), camera=()")

    @override_settings(AFRIBOUNTY_ENVIRONMENT="production", RATE_LIMIT_AUTH_REQUESTS=1, RATE_LIMIT_AUTH_WINDOW_SECONDS=60)
    def test_sensitive_rate_limit_refuses_burst(self):
        class FakeLimiter:
            def __init__(self):
                self.count = 0

            def hit(self, **_kwargs):
                self.count += 1
                return type("Decision", (), {"allowed": self.count == 1, "remaining": 0, "retry_after_seconds": 30})()

        middleware = SensitiveRateLimitMiddleware(lambda _request: HttpResponse("ok"))
        middleware._limiter = FakeLimiter()
        factory = RequestFactory()
        allowed = middleware(factory.get("/access/login/", REMOTE_ADDR="192.0.2.10"))
        blocked = middleware(factory.get("/access/login/", REMOTE_ADDR="192.0.2.10"))
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(allowed["X-RateLimit-Remaining"], "0")
        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(blocked["Retry-After"], "30")

    @override_settings(AFRIBOUNTY_ENVIRONMENT="production", RATE_LIMIT_API_KEY_REQUESTS=1, RATE_LIMIT_API_KEY_WINDOW_SECONDS=60)
    def test_api_key_rate_limit_uses_only_a_one_way_bearer_fingerprint(self):
        class FakeLimiter:
            def __init__(self):
                self.keys = []

            def hit(self, **kwargs):
                self.keys.append(kwargs["key"])
                return type("Decision", (), {"allowed": True, "remaining": 0, "retry_after_seconds": 60})()

        raw_key = "abk_this_must_not_be_stored_in_the_limiter_key"
        middleware = SensitiveRateLimitMiddleware(lambda _request: HttpResponse("ok"))
        middleware._limiter = FakeLimiter()
        response = middleware(RequestFactory().get("/api/v1/key/", HTTP_AUTHORIZATION=f"Bearer {raw_key}", REMOTE_ADDR="192.0.2.11"))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(raw_key, middleware._limiter.keys[0])
        self.assertTrue(middleware._limiter.keys[0].startswith("api-key:192.0.2.11:"))

    def test_metrics_are_non_sensitive_and_readiness_has_no_secret(self):
        client = APIClient()
        metrics = client.get("/metrics/")
        readiness = client.get("/health/ready/")
        self.assertEqual(metrics.status_code, 200)
        self.assertFalse(metrics.json()["contains_sensitive_data"])
        self.assertIn("http_requests_total", metrics.json()["counters"])
        self.assertEqual(readiness.status_code, 200)
        self.assertNotIn("password", str(readiness.json()).lower())

    @override_settings(AFRIBOUNTY_ENVIRONMENT="production", METRICS_AUTH_TOKEN="m" * 32)
    def test_production_metrics_and_readiness_require_distinct_token(self):
        client = APIClient()
        self.assertEqual(client.get("/metrics/").status_code, 403)
        authorized = client.get("/metrics/", HTTP_X_OBSERVABILITY_TOKEN="m" * 32)
        self.assertEqual(authorized.status_code, 200)
        self.assertEqual(client.get("/health/ready/").status_code, 403)

    @override_settings(AFRIBOUNTY_ENVIRONMENT="production", METRICS_AUTH_TOKEN="m" * 32)
    @patch("apps.security.views._dependency_status", return_value=({"database": "unavailable"}, False))
    def test_production_readiness_fails_closed_without_internal_error_details(self, _dependency_status):
        response = APIClient().get("/health/ready/", HTTP_X_OBSERVABILITY_TOKEN="m" * 32)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["status"], "unavailable")
        self.assertNotIn("exception", str(response.json()).lower())
        self.assertNotIn("password", str(response.json()).lower())


class AuditAndRetentionTests(TestCase):
    def test_audit_event_is_correlated_and_cannot_be_modified_or_deleted(self):
        token = correlation_id.set("corr-audit-001")
        try:
            event = record_audit(
                action="test.created",
                resource_type="test_resource",
                resource_reference="resource-001",
            )
        finally:
            correlation_id.reset(token)
        self.assertEqual(event.correlation_id, "corr-audit-001")
        self.assertEqual(len(event.integrity_signature), 64)
        self.assertTrue(verify_audit_event(event))
        event.action = "tampered"
        with self.assertRaises(ValidationError):
            event.save()
        with self.assertRaises(ValidationError):
            event.delete()
        self.assertEqual(AuditEvent.objects.count(), 1)

    def test_audit_integrity_command_detects_database_level_tampering(self):
        event = record_audit(action="test.created", resource_type="test_resource", resource_reference="resource-integrity-001")
        call_command("verify_audit_integrity", "--strict")
        AuditEvent.objects.filter(pk=event.pk).update(action="tampered-through-queryset")
        with self.assertRaises(CommandError):
            call_command("verify_audit_integrity", "--strict")

    def test_expired_record_is_anonymized_and_audited_not_deleted(self):
        expired = RetentionRecord.objects.create(
            category="security_notification",
            subject_reference="subject-001",
            payload={"email": "not-an-email-in-production"},
            expires_at=timezone.now() - timedelta(days=1),
        )
        active = RetentionRecord.objects.create(
            category="security_notification",
            subject_reference="subject-002",
            payload={"status": "active"},
            expires_at=timezone.now() + timedelta(days=1),
        )
        self.assertEqual(anonymize_expired_records(), 1)
        expired.refresh_from_db()
        active.refresh_from_db()
        self.assertEqual(expired.payload, {"status": "anonymized"})
        self.assertEqual(expired.subject_reference, "anonymized")
        self.assertIsNotNone(expired.anonymized_at)
        self.assertIsNone(active.anonymized_at)
        self.assertEqual(AuditEvent.objects.filter(action="retention.anonymized").count(), 1)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
    def test_retention_task_runs_in_eager_mode(self):
        RetentionRecord.objects.create(
            category="security_notification",
            subject_reference="subject-003",
            payload={"status": "expired"},
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        result = retention_anonymization_task.apply().get()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["anonymized_records"], 1)


class SecurityControlTests(TestCase):
    def test_rate_limiter_blocks_burst_and_resets_after_window(self):
        limiter = MemoryRateLimiter()
        first = limiter.hit(key="ip:127.0.0.1", limit=2, window_seconds=60, now=1000)
        second = limiter.hit(key="ip:127.0.0.1", limit=2, window_seconds=60, now=1001)
        blocked = limiter.hit(key="ip:127.0.0.1", limit=2, window_seconds=60, now=1002)
        reset = limiter.hit(key="ip:127.0.0.1", limit=2, window_seconds=60, now=1061)
        self.assertTrue(first.allowed)
        self.assertTrue(second.allowed)
        self.assertFalse(blocked.allowed)
        self.assertTrue(reset.allowed)

    @override_settings(AFRIBOUNTY_ENVIRONMENT="test", RATE_LIMIT_BACKEND="memory")
    def test_memory_limiter_is_available_only_for_test_profile(self):
        self.assertIsInstance(create_rate_limiter(), MemoryRateLimiter)

    @override_settings(AFRIBOUNTY_ENVIRONMENT="development", RATE_LIMIT_BACKEND="memory")
    def test_memory_limiter_is_refused_outside_test_profile(self):
        with self.assertRaisesMessage(ImproperlyConfigured, "uniquement dans le profil de test"):
            create_rate_limiter()

    @override_settings(AFRIBOUNTY_ENVIRONMENT="production", RATE_LIMIT_BACKEND="redis", REDIS_URL="rediss://:placeholder@redis.example:6379/0")
    def test_redis_backend_uses_configured_private_client_or_explicit_client(self):
        self.assertIsInstance(create_rate_limiter(), RedisRateLimiter)

        class FakeRedis:
            def eval(self, script, keys, key, window):
                return [1, 60]

        self.assertIsInstance(create_rate_limiter(redis_client=FakeRedis()), RedisRateLimiter)

    def test_frozen_subject_is_blocked_and_action_is_audited(self):
        subject = SecuritySubject.objects.create(reference="subject-freeze-001")
        assert_subject_active(subject)
        freeze_subject(subject=subject, reason="Revue nécessaire", actor_reference="operator-001")
        subject.refresh_from_db()
        self.assertEqual(subject.status, SecuritySubject.Status.FROZEN)
        self.assertTrue(subject.review_required)
        with self.assertRaises(AccountFrozen):
            assert_subject_active(subject)
        self.assertEqual(AuditEvent.objects.filter(action="security_subject.frozen").count(), 1)

    def test_security_notification_refuses_sensitive_context(self):
        message = render_security_notification(template="account_frozen", context={"reference": "review-001"})
        self.assertIn("review-001", message)
        with self.assertRaises(ForbiddenNotificationContext):
            render_security_notification(template="account_frozen", context={"reference": "review-001", "token": "forbidden"})
