import secrets

from django.conf import settings
from django.db import connection
from redis import Redis
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.core.correlation import current_correlation_id
from apps.security.operational_metrics import operational_metrics_snapshot


def _require_observability_token(request) -> None:
    if settings.AFRIBOUNTY_ENVIRONMENT != "production":
        return
    supplied = request.headers.get("X-Observability-Token", "")
    if not supplied or not secrets.compare_digest(supplied, settings.METRICS_AUTH_TOKEN):
        raise PermissionDenied("Jeton d’observabilité requis.")


def _dependency_status() -> tuple[dict[str, str], bool]:
    """Vérifie les dépendances sans exposer les détails d’exception au client."""
    checks: dict[str, str] = {}
    healthy = True
    try:
        connection.ensure_connection()
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "unavailable"
        healthy = False

    if not settings.READINESS_CHECK_EXTERNAL_DEPENDENCIES:
        checks["external_dependencies"] = "not_checked_in_this_profile"
        return checks, healthy

    redis_client = Redis.from_url(settings.REDIS_URL, socket_connect_timeout=1, socket_timeout=1)
    try:
        redis_client.ping()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "unavailable"
        healthy = False
    finally:
        redis_client.close()
    return checks, healthy


@api_view(["GET"])
@permission_classes([AllowAny])
def live(request):
    return Response({"status": "ok", "service": "afribounty", "correlation_id": current_correlation_id()})


@api_view(["GET"])
@permission_classes([AllowAny])
def ready(request):
    _require_observability_token(request)
    checks, healthy = _dependency_status()
    return Response(
        {
            "status": "ok" if healthy else "unavailable",
            "checks": checks,
            "correlation_id": current_correlation_id(),
        },
        status=200 if healthy else 503,
    )


@api_view(["GET"])
@permission_classes([AllowAny])
def metrics(request):
    _require_observability_token(request)
    return Response(
        {
            "service": "afribounty",
            "metric_schema_version": "1",
            "contains_sensitive_data": False,
            "counters": operational_metrics_snapshot(),
            "correlation_id": current_correlation_id(),
        }
    )
