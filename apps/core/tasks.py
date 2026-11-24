from datetime import UTC, datetime

from celery import shared_task

from apps.core.correlation import current_correlation_id


@shared_task(bind=True, autoretry_for=(), acks_late=True)
def diagnostic_task(self, correlation: str = "") -> dict[str, str]:
    """Tâche non destructive confirmant le câblage Celery et la corrélation."""
    return {
        "status": "ok",
        "task_id": self.request.id or "eager",
        "correlation_id": correlation or current_correlation_id() or "not-provided",
        "executed_at": datetime.now(UTC).isoformat(),
    }
