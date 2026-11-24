"""Contrat de fournisseur de paiement sandboxé, sans réseau ni transfert monétaire réel."""

import hashlib
import hmac
import json
from dataclasses import dataclass
from uuid import uuid4

from django.core.exceptions import ValidationError


def canonical_webhook_payload(*, event_id: str, provider_reference: str, status: str, occurred_at: str) -> str:
    return json.dumps(
        {"event_id": event_id, "occurred_at": occurred_at, "provider_reference": provider_reference, "status": status},
        sort_keys=True,
        separators=(",", ":"),
    )


@dataclass(frozen=True)
class SandboxSubmission:
    provider_reference: str
    status: str


class SandboxPaymentProvider:
    provider_code = "sandbox-money"

    def __init__(self, signing_secret: str):
        if len(signing_secret) < 16:
            raise ValidationError("Le secret de signature sandbox doit être suffisamment long.")
        self._secret = signing_secret.encode()
        self._orders: dict[str, SandboxSubmission] = {}

    def submit(self, *, idempotency_key: str, amount_xof: int, beneficiary_reference: str) -> SandboxSubmission:
        if amount_xof <= 0 or not beneficiary_reference.strip():
            raise ValidationError("Le montant et la référence bénéficiaire sandbox sont obligatoires.")
        existing = self._orders.get(idempotency_key)
        if existing:
            return existing
        submission = SandboxSubmission(provider_reference=f"sandbox-pay-{uuid4().hex}", status="submitted")
        self._orders[idempotency_key] = submission
        return submission

    def sign_webhook(self, *, event_id: str, provider_reference: str, status: str, occurred_at: str) -> str:
        return hmac.new(
            self._secret,
            canonical_webhook_payload(
                event_id=event_id,
                provider_reference=provider_reference,
                status=status,
                occurred_at=occurred_at,
            ).encode(),
            hashlib.sha256,
        ).hexdigest()

    def verify_webhook(self, *, event_id: str, provider_reference: str, status: str, occurred_at: str, signature: str) -> bool:
        expected = self.sign_webhook(event_id=event_id, provider_reference=provider_reference, status=status, occurred_at=occurred_at)
        return hmac.compare_digest(expected, signature)
