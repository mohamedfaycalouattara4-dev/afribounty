import json
import logging

from django.test import SimpleTestCase, override_settings
from rest_framework.test import APIClient

from apps.core.correlation import correlation_id
from apps.core.logging import JsonFormatter
from apps.core.tasks import diagnostic_task


class RuntimeServiceTests(SimpleTestCase):
    @override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
    def test_diagnostic_task_returns_json_compatible_result_with_correlation(self):
        result = diagnostic_task.apply(kwargs={"correlation": "corr-test-0001"}).get()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["correlation_id"], "corr-test-0001")
        self.assertIn("executed_at", result)

    def test_json_logs_include_correlation_id_without_request_content(self):
        token = correlation_id.set("corr-log-0001")
        try:
            record = logging.LogRecord("afribounty.test", logging.INFO, __file__, 0, "diagnostic terminé", (), None)
            payload = json.loads(JsonFormatter().format(record))
        finally:
            correlation_id.reset(token)
        self.assertEqual(payload["correlation_id"], "corr-log-0001")
        self.assertEqual(payload["message"], "diagnostic terminé")
        self.assertNotIn("request_body", payload)

    def test_health_endpoint_returns_and_echoes_correlation_identifier(self):
        response = APIClient().get("/health/", HTTP_X_CORRELATION_ID="corr-http-0001")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")
        self.assertEqual(response["X-Correlation-ID"], "corr-http-0001")
        self.assertEqual(response.json()["correlation_id"], "corr-http-0001")
