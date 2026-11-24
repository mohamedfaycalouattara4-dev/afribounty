from celery import shared_task

from apps.security.retention import anonymize_expired_records


@shared_task(bind=True, autoretry_for=(), acks_late=True)
def retention_anonymization_task(self) -> dict[str, int | str]:
    count = anonymize_expired_records()
    return {"status": "ok", "anonymized_records": count, "task_id": self.request.id or "eager"}
