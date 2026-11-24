from django.utils import timezone

from apps.security.audit import record_audit
from apps.security.models import RetentionRecord


def anonymize_expired_records(*, now=None) -> int:
    execution_time = now or timezone.now()
    records = RetentionRecord.objects.filter(expires_at__lte=execution_time, anonymized_at__isnull=True)
    count = 0
    for record in records.iterator():
        record.payload = {"status": "anonymized"}
        record.subject_reference = "anonymized"
        record.anonymized_at = execution_time
        record.save(update_fields=["payload", "subject_reference", "anonymized_at"])
        record_audit(
            action="retention.anonymized",
            resource_type="retention_record",
            resource_reference=str(record.pk),
        )
        count += 1
    return count
