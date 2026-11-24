from django.core.exceptions import PermissionDenied, ValidationError
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.identity.services import has_platform_permission
from apps.reports.models import Report, TriageDecision
from apps.rewards.models import (
    BeneficiaryProfile,
    LedgerEntry,
    PaymentOrder,
    PaymentWebhookEvent,
    ReconciliationReport,
    RewardApproval,
    RewardEntitlement,
)
from apps.rewards.sandbox import SandboxPaymentProvider
from apps.security.action_gate import require_adaptive_action


DOUBLE_CONTROL_THRESHOLD_XOF = 100_000


def _require_sandbox_environment() -> None:
    if settings.AFRIBOUNTY_ENVIRONMENT == "production":
        raise ImproperlyConfigured("Les adaptateurs de paiement sandbox sont interdits en production.")


def _require_finance(*, user) -> None:
    if not has_platform_permission(user=user, permission="reward.approve"):
        raise PermissionDenied("Un rôle finance autorisé est obligatoire.")


@transaction.atomic
def create_reward_entitlement(*, report: Report, proposer, amount_xof: int, rationale: str) -> RewardEntitlement:
    if report.status != Report.Status.VALID:
        raise ValidationError("Un droit à récompense exige un rapport accepté et valide.")
    decision = getattr(report, "triage_decision", None)
    if not decision or decision.reward_eligibility != TriageDecision.RewardEligibility.ELIGIBLE:
        raise ValidationError("La récompense nécessite une décision de triage explicitement éligible.")
    if amount_xof <= 0 or not rationale.strip():
        raise ValidationError("Le montant et la justification de récompense sont obligatoires.")
    entitlement, created = RewardEntitlement.objects.get_or_create(
        report=report,
        defaults={"beneficiary": report.author, "proposed_by": proposer, "amount_xof": amount_xof, "rationale": rationale.strip()},
    )
    if not created and (entitlement.amount_xof != amount_xof or entitlement.beneficiary_id != report.author_id):
        raise ValidationError("Un droit existe déjà avec des paramètres différents.")
    return entitlement


@transaction.atomic
def approve_reward(*, entitlement: RewardEntitlement, approver, approved: bool, reason: str) -> RewardEntitlement:
    _require_finance(user=approver)
    if entitlement.status != RewardEntitlement.Status.PENDING:
        raise ValidationError("Seul un droit à récompense en attente peut être approuvé.")
    if approver.id == entitlement.proposed_by_id:
        raise PermissionDenied("Le proposeur ne peut pas approuver sa propre récompense.")
    if not reason.strip():
        raise ValidationError("Toute approbation ou tout refus exige un motif.")
    RewardApproval.objects.create(entitlement=entitlement, approver=approver, approved=approved, reason=reason.strip())
    if not approved:
        entitlement.status = RewardEntitlement.Status.CANCELLED
        entitlement.save(update_fields=["status"])
        return entitlement
    approvals = entitlement.approvals.filter(approved=True).count()
    required = 2 if entitlement.amount_xof >= DOUBLE_CONTROL_THRESHOLD_XOF else 1
    if approvals >= required:
        entitlement.status = RewardEntitlement.Status.APPROVED
        entitlement.approved_at = timezone.now()
        entitlement.save(update_fields=["status", "approved_at"])
        append_ledger_entry(
            entitlement=entitlement,
            entry_type=LedgerEntry.EntryType.PROMISE,
            amount_xof=entitlement.amount_xof,
            reference=f"reward-entitlement:{entitlement.id}",
            idempotency_key=f"ledger:promise:{entitlement.id}",
            actor=approver,
        )
    return entitlement


@transaction.atomic
def append_ledger_entry(
    *,
    entitlement: RewardEntitlement,
    entry_type: str,
    amount_xof: int,
    reference: str,
    idempotency_key: str,
    actor=None,
    compensates=None,
) -> LedgerEntry:
    if not reference.strip() or not idempotency_key.strip() or amount_xof == 0:
        raise ValidationError("Toute écriture exige montant non nul, référence et clé d’idempotence.")
    entry, _ = LedgerEntry.objects.get_or_create(
        idempotency_key=idempotency_key.strip(),
        defaults={
            "entitlement": entitlement,
            "entry_type": entry_type,
            "amount_xof": amount_xof,
            "reference": reference.strip(),
            "created_by": actor,
            "compensates": compensates,
        },
    )
    if entry.entitlement_id != entitlement.id:
        raise ValidationError("La clé d’idempotence du grand livre pointe vers une autre récompense.")
    return entry


@transaction.atomic
def cancel_reward(*, entitlement: RewardEntitlement, actor, reason: str) -> LedgerEntry:
    _require_finance(user=actor)
    if entitlement.status not in {RewardEntitlement.Status.PENDING, RewardEntitlement.Status.APPROVED} or not reason.strip():
        raise ValidationError("L’annulation exige une récompense active et un motif.")
    promise = entitlement.ledger_entries.filter(entry_type=LedgerEntry.EntryType.PROMISE).first()
    if not promise:
        raise ValidationError("Une récompense ne peut être annulée sans promesse de grand livre.")
    entry = append_ledger_entry(
        entitlement=entitlement,
        entry_type=LedgerEntry.EntryType.CANCELLATION,
        amount_xof=-promise.amount_xof,
        reference=f"reward-cancel:{entitlement.id}:{reason.strip()[:40]}",
        idempotency_key=f"ledger:cancel:{entitlement.id}",
        actor=actor,
        compensates=promise,
    )
    entitlement.status = RewardEntitlement.Status.CANCELLED
    entitlement.save(update_fields=["status"])
    return entry


@transaction.atomic
def record_sandbox_fee(*, entitlement: RewardEntitlement, actor, amount_xof: int, reference: str) -> LedgerEntry:
    _require_sandbox_environment()
    _require_finance(user=actor)
    if entitlement.status != RewardEntitlement.Status.APPROVED or amount_xof <= 0:
        raise ValidationError("Les frais exigent une récompense approuvée et un montant positif.")
    return append_ledger_entry(
        entitlement=entitlement,
        entry_type=LedgerEntry.EntryType.FEE,
        amount_xof=-amount_xof,
        reference=reference,
        idempotency_key=f"ledger:fee:{entitlement.id}:{reference}",
        actor=actor,
    )


def set_beneficiary_profile(*, user, provider_code: str, recipient_reference: str) -> BeneficiaryProfile:
    _require_sandbox_environment()
    require_adaptive_action(user=user, action="beneficiary.change")
    if provider_code != "sandbox-money" or not recipient_reference.strip():
        raise ValidationError("Seul le fournisseur sandbox et une référence non vide sont admis dans ce lot.")
    with transaction.atomic():
        profile, _ = BeneficiaryProfile.objects.update_or_create(
            user=user,
            defaults={
                "provider_code": provider_code,
                "recipient_reference": recipient_reference.strip(),
                "verification_status": BeneficiaryProfile.VerificationStatus.PENDING,
                "verified_by": None,
                "verified_at": None,
            },
        )
    return profile


@transaction.atomic
def verify_beneficiary(*, profile: BeneficiaryProfile, reviewer) -> BeneficiaryProfile:
    _require_finance(user=reviewer)
    if reviewer.id == profile.user_id:
        raise PermissionDenied("Un bénéficiaire ne peut pas vérifier son propre profil.")
    profile.verification_status = BeneficiaryProfile.VerificationStatus.VERIFIED
    profile.verified_by = reviewer
    profile.verified_at = timezone.now()
    profile.save(update_fields=["verification_status", "verified_by", "verified_at", "updated_at"])
    return profile


@transaction.atomic
def create_payment_order(*, entitlement: RewardEntitlement, actor, idempotency_key: str, provider: SandboxPaymentProvider) -> PaymentOrder:
    _require_sandbox_environment()
    _require_finance(user=actor)
    if entitlement.status != RewardEntitlement.Status.APPROVED:
        raise ValidationError("Un paiement exige une récompense approuvée.")
    profile = getattr(entitlement.beneficiary, "beneficiary_profile", None)
    if not profile or profile.verification_status != BeneficiaryProfile.VerificationStatus.VERIFIED:
        raise ValidationError("Le bénéficiaire doit être vérifié avant création du paiement.")
    if not idempotency_key.strip():
        raise ValidationError("Une clé d’idempotence de paiement est obligatoire.")
    existing = PaymentOrder.objects.filter(idempotency_key=idempotency_key.strip()).first()
    if existing:
        if existing.entitlement_id != entitlement.id:
            raise ValidationError("La clé d’idempotence est déjà associée à une autre récompense.")
        return existing
    submission = provider.submit(idempotency_key=idempotency_key.strip(), amount_xof=entitlement.amount_xof, beneficiary_reference=profile.recipient_reference)
    order = PaymentOrder.objects.create(
        entitlement=entitlement,
        beneficiary=profile,
        amount_xof=entitlement.amount_xof,
        idempotency_key=idempotency_key.strip(),
        provider_code=provider.provider_code,
        provider_reference=submission.provider_reference,
        status=PaymentOrder.Status.SUBMITTED,
    )
    return order


@transaction.atomic
def process_payment_webhook(
    *,
    provider: SandboxPaymentProvider,
    event_id: str,
    provider_reference: str,
    status: str,
    occurred_at,
    signature: str,
) -> PaymentOrder:
    _require_sandbox_environment()
    if not event_id.strip() or PaymentWebhookEvent.objects.filter(event_id=event_id).exists():
        raise PermissionDenied("Le webhook est dupliqué ou ne possède pas d’identifiant.")
    now = timezone.now()
    if abs((now - occurred_at).total_seconds()) > 300:
        raise PermissionDenied("Le webhook sandbox est expiré ou présente un horodatage invalide.")
    timestamp = occurred_at.isoformat()
    if not provider.verify_webhook(event_id=event_id, provider_reference=provider_reference, status=status, occurred_at=timestamp, signature=signature):
        raise PermissionDenied("La signature du webhook sandbox est invalide.")
    order = PaymentOrder.objects.select_for_update().get(provider_reference=provider_reference, provider_code=provider.provider_code)
    if status not in {"succeeded", "failed"}:
        raise ValidationError("Le statut de paiement sandbox est inconnu.")
    PaymentWebhookEvent.objects.create(
        provider_code=provider.provider_code,
        event_id=event_id,
        provider_reference=provider_reference,
        payload={"status": status},
        signature=signature,
        occurred_at=occurred_at,
    )
    if status == "succeeded":
        order.status = PaymentOrder.Status.SUCCEEDED
        append_ledger_entry(
            entitlement=order.entitlement,
            entry_type=LedgerEntry.EntryType.PAYMENT,
            amount_xof=-order.amount_xof,
            reference=f"payment:{order.provider_reference}",
            idempotency_key=f"ledger:payment:{order.id}",
        )
    else:
        order.status = PaymentOrder.Status.FAILED
    order.save(update_fields=["status", "updated_at"])
    return order


@transaction.atomic
def reconcile_sandbox_payments(*, actor, provider_code: str = "sandbox-money") -> ReconciliationReport:
    _require_sandbox_environment()
    _require_finance(user=actor)
    orders = PaymentOrder.objects.filter(provider_code=provider_code)
    succeeded = orders.filter(status=PaymentOrder.Status.SUCCEEDED)
    missing_ledger = [
        order.provider_reference for order in succeeded if not order.entitlement.ledger_entries.filter(entry_type=LedgerEntry.EntryType.PAYMENT).exists()
    ]
    payload = {
        "orders_total": orders.count(),
        "orders_succeeded": succeeded.count(),
        "orders_failed": orders.filter(status=PaymentOrder.Status.FAILED).count(),
        "amount_succeeded_xof": succeeded.aggregate(total=Sum("amount_xof"))["total"] or 0,
        "missing_payment_ledger_references": missing_ledger,
    }
    return ReconciliationReport.objects.create(provider_code=provider_code, aggregate=payload, exception_count=len(missing_ledger), created_by=actor)
