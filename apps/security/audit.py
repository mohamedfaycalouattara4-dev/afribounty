import hashlib
import hmac
import json
from uuid import uuid4

from django.conf import settings

from apps.core.correlation import current_correlation_id
from apps.security.models import AuditEvent


def _canonical_audit_payload(
    *, action: str, resource_type: str, resource_reference: str, actor_reference: str, metadata: dict, correlation_id: str, event_nonce: str
) -> str:
    return json.dumps(
        {
            "action": action,
            "resource_type": resource_type,
            "resource_reference": resource_reference,
            "actor_reference": actor_reference,
            "metadata": metadata,
            "correlation_id": correlation_id,
            "event_nonce": event_nonce,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _sign_audit_hash(integrity_hash: str) -> str:
    return hmac.new(settings.AUDIT_INTEGRITY_KEY.encode("utf-8"), integrity_hash.encode("ascii"), hashlib.sha256).hexdigest()


def verify_audit_event(event: AuditEvent) -> bool:
    canonical = _canonical_audit_payload(
        action=event.action,
        resource_type=event.resource_type,
        resource_reference=event.resource_reference,
        actor_reference=event.actor_reference,
        metadata=event.metadata,
        correlation_id=event.correlation_id,
        event_nonce=event.event_nonce,
    )
    expected_hash = hashlib.sha256(canonical.encode()).hexdigest()
    expected_signature = _sign_audit_hash(expected_hash)
    return (
        bool(event.integrity_signature)
        and hmac.compare_digest(event.integrity_hash, expected_hash)
        and hmac.compare_digest(event.integrity_signature, expected_signature)
    )


def audit_integrity_report() -> dict:
    """Retourne uniquement des compteurs locaux ; les événements et leurs métadonnées restent confidentiels."""
    checked_count = 0
    invalid_count = 0
    for event in AuditEvent.objects.iterator():
        checked_count += 1
        if not verify_audit_event(event):
            invalid_count += 1
    return {"checked_count": checked_count, "invalid_count": invalid_count, "valid": invalid_count == 0}


def record_audit(
    *,
    action: str,
    resource_type: str,
    resource_reference: str,
    actor_reference: str = "",
    metadata: dict | None = None,
) -> AuditEvent:
    safe_metadata = metadata or {}
    event_nonce = uuid4().hex
    resolved_correlation_id = current_correlation_id() or "not-provided"
    canonical = _canonical_audit_payload(
        action=action,
        resource_type=resource_type,
        resource_reference=resource_reference,
        actor_reference=actor_reference,
        metadata=safe_metadata,
        correlation_id=resolved_correlation_id,
        event_nonce=event_nonce,
    )
    integrity_hash = hashlib.sha256(canonical.encode()).hexdigest()
    return AuditEvent.objects.create(
        action=action,
        resource_type=resource_type,
        resource_reference=resource_reference,
        actor_reference=actor_reference,
        correlation_id=resolved_correlation_id,
        metadata=safe_metadata,
        event_nonce=event_nonce,
        integrity_hash=integrity_hash,
        integrity_signature=_sign_audit_hash(integrity_hash),
    )
