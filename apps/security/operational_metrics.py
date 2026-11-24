from django.core.cache import cache


PREFIX = "afribounty:operational-metrics:"
COUNTERS = ("http_requests_total", "http_errors_5xx_total", "sensitive_requests_total")


def record_http_response(*, status_code: int, sensitive: bool) -> None:
    try:
        cache.incr(f"{PREFIX}http_requests_total")
    except Exception:
        try:
            cache.set(f"{PREFIX}http_requests_total", 1, timeout=None)
        except Exception:
            return
    if status_code >= 500:
        try:
            cache.incr(f"{PREFIX}http_errors_5xx_total")
        except Exception:
            try:
                cache.set(f"{PREFIX}http_errors_5xx_total", 1, timeout=None)
            except Exception:
                return
    if sensitive:
        try:
            cache.incr(f"{PREFIX}sensitive_requests_total")
        except Exception:
            try:
                cache.set(f"{PREFIX}sensitive_requests_total", 1, timeout=None)
            except Exception:
                return


def operational_metrics_snapshot() -> dict[str, int]:
    try:
        return {counter: int(cache.get(f"{PREFIX}{counter}", 0) or 0) for counter in COUNTERS}
    except Exception:
        return {counter: 0 for counter in COUNTERS}
