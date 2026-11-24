from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.integrations.models import LocalNotification


@transaction.atomic
def create_local_notification(*, user, event_type: str, title: str, body: str, safe_reference: str, idempotency_key: str):
    if event_type not in dict(LocalNotification.EventType.choices):
        raise ValidationError("Le type de notification locale est invalide.")
    if not all([title.strip(), body.strip(), safe_reference.strip(), idempotency_key.strip()]):
        raise ValidationError("Toute notification locale exige un libellé, un message, une référence et une clé.")
    notification, created = LocalNotification.objects.get_or_create(
        idempotency_key=idempotency_key.strip(),
        defaults={
            "user": user,
            "event_type": event_type,
            "title": title.strip()[:160],
            "body": body.strip()[:500],
            "safe_reference": safe_reference.strip()[:128],
        },
    )
    if notification.user_id != user.id:
        raise ValidationError("La clé de notification est déjà rattachée à un autre compte.")
    return notification, created


@transaction.atomic
def mark_local_notification_read(*, user, notification_id: int | None = None) -> int:
    notifications = LocalNotification.objects.filter(user=user, read_at__isnull=True)
    if notification_id is not None:
        notifications = notifications.filter(pk=notification_id)
    return notifications.update(read_at=timezone.now())
