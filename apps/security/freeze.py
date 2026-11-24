from django.utils import timezone

from apps.security.audit import record_audit
from apps.security.exceptions import AccountFrozen
from apps.security.models import SecuritySubject


def freeze_subject(*, subject: SecuritySubject, reason: str, actor_reference: str) -> SecuritySubject:
    subject.status = SecuritySubject.Status.FROZEN
    subject.frozen_reason = reason.strip()
    subject.frozen_at = timezone.now()
    subject.review_required = True
    subject.save(update_fields=["status", "frozen_reason", "frozen_at", "review_required"])
    record_audit(
        action="security_subject.frozen",
        resource_type="security_subject",
        resource_reference=subject.reference,
        actor_reference=actor_reference,
    )
    return subject


def assert_subject_active(subject: SecuritySubject) -> None:
    if subject.status == SecuritySubject.Status.FROZEN:
        raise AccountFrozen("Cette action est bloquée jusqu’à la revue humaine.")
