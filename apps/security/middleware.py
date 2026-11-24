from django.http import HttpRequest, HttpResponse

import hashlib

from django.conf import settings
from django.http import JsonResponse

from apps.security.operational_metrics import record_http_response
from apps.security.rate_limit import create_rate_limiter


class SensitiveRateLimitMiddleware:
    """Limite les routes coûteuses ou exposées aux abus ; Redis est obligatoire en production."""

    AUTH_PREFIXES = ("/access/login/", "/access/signup/", "/access/recover/")
    UPLOAD_SUFFIX = "/evidence/"
    API_KEY_PATH = "/api/v1/key/"

    def __init__(self, get_response):
        self.get_response = get_response
        self._limiter = None

    def _rule_for(self, path: str) -> tuple[str, int, int] | None:
        if path.startswith(self.AUTH_PREFIXES):
            return ("auth", settings.RATE_LIMIT_AUTH_REQUESTS, settings.RATE_LIMIT_AUTH_WINDOW_SECONDS)
        if path.endswith(self.UPLOAD_SUFFIX):
            return ("evidence", settings.RATE_LIMIT_UPLOAD_REQUESTS, settings.RATE_LIMIT_UPLOAD_WINDOW_SECONDS)
        if path == self.API_KEY_PATH:
            return ("api-key", settings.RATE_LIMIT_API_KEY_REQUESTS, settings.RATE_LIMIT_API_KEY_WINDOW_SECONDS)
        return None

    @staticmethod
    def _subject_for(request, category: str) -> str:
        address = request.META.get("REMOTE_ADDR", "unknown")[:96]
        if category != "api-key":
            return address
        authorization = request.headers.get("Authorization", "")
        fingerprint = hashlib.sha256(authorization.encode()).hexdigest()[:32] if authorization.startswith("Bearer ") else "anonymous"
        return f"{address}:{fingerprint}"

    def __call__(self, request):
        if settings.AFRIBOUNTY_ENVIRONMENT != "production":
            return self.get_response(request)
        rule = self._rule_for(request.path)
        if rule is None:
            return self.get_response(request)
        if self._limiter is None:
            self._limiter = create_rate_limiter()
        category, limit, window = rule
        subject = self._subject_for(request, category)
        try:
            decision = self._limiter.hit(key=f"{category}:{subject}", limit=limit, window_seconds=window)
        except Exception:
            return JsonResponse({"detail": "Contrôle de débit indisponible ; action sensible temporairement refusée."}, status=503)
        if not decision.allowed:
            response = JsonResponse({"detail": "Trop de tentatives. Réessayez plus tard."}, status=429)
            response["Retry-After"] = str(max(1, decision.retry_after_seconds))
            return response
        response = self.get_response(request)
        response["X-RateLimit-Remaining"] = str(decision.remaining)
        return response


class OperationalMetricsMiddleware:
    """Agrège les requêtes par statut sans conserver URL, corps ni identité utilisateur."""

    SENSITIVE_PREFIXES = ("/access/", "/reports/", "/console/", "/settings/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.path != "/metrics/":
            record_http_response(
                status_code=response.status_code,
                sensitive=request.path.startswith(self.SENSITIVE_PREFIXES),
            )
        return response


class HttpSecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        response["Content-Security-Policy"] = (
            f"default-src {' '.join(settings.CSP_DEFAULT_SRC)}; "
            f"base-uri {' '.join(settings.CSP_BASE_URI)}; "
            f"frame-ancestors {' '.join(settings.CSP_FRAME_ANCESTORS)}; "
            f"object-src {' '.join(settings.CSP_OBJECT_SRC)}; "
            f"form-action {' '.join(settings.CSP_FORM_ACTION)}"
        )
        response["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        response["Cross-Origin-Opener-Policy"] = "same-origin"
        response["Cross-Origin-Resource-Policy"] = "same-origin"
        response["X-Content-Type-Options"] = "nosniff"
        return response
