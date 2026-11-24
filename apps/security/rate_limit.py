from dataclasses import dataclass
from time import time

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from redis import Redis


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    remaining: int
    retry_after_seconds: int


class MemoryRateLimiter:
    """Repli déterministe réservé aux tests ; interdit comme mécanisme de production."""

    def __init__(self):
        self._buckets: dict[str, tuple[int, float]] = {}

    def hit(self, *, key: str, limit: int, window_seconds: int, now: float | None = None) -> RateLimitDecision:
        current_time = now if now is not None else time()
        used, expires_at = self._buckets.get(key, (0, current_time + window_seconds))
        if current_time >= expires_at:
            used, expires_at = 0, current_time + window_seconds
        used += 1
        self._buckets[key] = (used, expires_at)
        allowed = used <= limit
        return RateLimitDecision(
            allowed=allowed,
            remaining=max(0, limit - used),
            retry_after_seconds=max(0, int(expires_at - current_time)),
        )


class RedisRateLimiter:
    """Compteur INCR/EXPIRE atomique ; nécessite Redis privé hors test."""

    SCRIPT = """
    local current = redis.call('INCR', KEYS[1])
    if current == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
    local ttl = redis.call('TTL', KEYS[1])
    return {current, ttl}
    """

    def __init__(self, client, prefix: str):
        self.client = client
        self.prefix = prefix

    def hit(self, *, key: str, limit: int, window_seconds: int) -> RateLimitDecision:
        count, ttl = self.client.eval(self.SCRIPT, 1, f"{self.prefix}{key}", window_seconds)
        return RateLimitDecision(
            allowed=int(count) <= limit,
            remaining=max(0, limit - int(count)),
            retry_after_seconds=max(0, int(ttl)),
        )


def create_rate_limiter(*, redis_client=None):
    """Sélection stricte : mémoire seulement en test, Redis obligatoire hors test."""
    if settings.RATE_LIMIT_BACKEND == "memory":
        if settings.AFRIBOUNTY_ENVIRONMENT != "test":
            raise ImproperlyConfigured("Le limiteur mémoire est autorisé uniquement dans le profil de test.")
        return MemoryRateLimiter()
    if settings.RATE_LIMIT_BACKEND == "redis":
        redis_client = redis_client or Redis.from_url(settings.REDIS_URL, socket_connect_timeout=1, socket_timeout=1)
        return RedisRateLimiter(client=redis_client, prefix=settings.RATE_LIMIT_REDIS_PREFIX)
    raise ImproperlyConfigured("Backend de limitation inconnu.")
