"""Politiques explicites de confirmation renforcée pour les actions locales sensibles."""

from dataclasses import dataclass
from uuid import uuid4

from django.core.exceptions import PermissionDenied, ValidationError

from apps.identity.models import AuthenticationEvent
from apps.identity.services import require_step_up


@dataclass(frozen=True)
class ActionGatePolicy:
    action: str
    label: str
    sensitivity: str
    step_up_action: str


@dataclass(frozen=True)
class ActionGateDecision:
    action: str
    label: str
    sensitivity: str
    allowed: bool
    reason_codes: tuple[str, ...]


ACTION_GATE_POLICIES = {
    "api_key.create": ActionGatePolicy("api_key.create", "Création de clé API", "high", "api_key.create"),
    "api_key.rotate": ActionGatePolicy("api_key.rotate", "Rotation de clé API", "high", "api_key.rotate"),
    "api_key.revoke": ActionGatePolicy("api_key.revoke", "Révocation de clé API", "high", "api_key.revoke"),
    "beneficiary.change": ActionGatePolicy("beneficiary.change", "Modification de bénéficiaire", "high", "beneficiary.change"),
    "program.emergency_suspend": ActionGatePolicy("program.emergency_suspend", "Suspension d’urgence de programme", "high", "program.emergency_suspend"),
    "program.emergency_resume": ActionGatePolicy("program.emergency_resume", "Reprise de programme suspendu", "high", "program.emergency_resume"),
}


def assess_adaptive_action(*, user, action: str) -> ActionGateDecision:
    policy = ACTION_GATE_POLICIES.get(action)
    if policy is None:
        raise ValidationError("La politique de garde d’action demandée est inconnue.")
    reason_codes = []
    try:
        require_step_up(user=user, action=policy.step_up_action)
    except PermissionDenied:
        reason_codes.append("recent_mfa_step_up_required")
    return ActionGateDecision(
        action=policy.action,
        label=policy.label,
        sensitivity=policy.sensitivity,
        allowed=not reason_codes,
        reason_codes=tuple(reason_codes),
    )


def require_adaptive_action(*, user, action: str) -> ActionGateDecision:
    decision = assess_adaptive_action(user=user, action=action)
    AuthenticationEvent.objects.create(
        user=user,
        event_type="action_gate.allowed" if decision.allowed else "action_gate.denied",
        correlation_id=uuid4().hex,
        metadata={
            "action": decision.action,
            "sensitivity": decision.sensitivity,
            "reason_codes": list(decision.reason_codes),
        },
    )
    if not decision.allowed:
        raise PermissionDenied(f"{decision.label} refusée : une vérification MFA récente est obligatoire.")
    return decision
