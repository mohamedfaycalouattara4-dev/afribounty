import hashlib
import json

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.identity.services import has_platform_permission
from apps.integrations.external_readiness import external_service_registry_integrity_report
from apps.readiness.models import GoNoGoAssessment, ReadinessCheck, ResilienceExercise
from apps.reports.evidence_pipeline import evidence_pipeline_contract_report
from apps.reports.services import evidence_integrity_report, report_scope_integrity_report
from apps.security.audit import audit_integrity_report
from apps.security.privilege_review import privilege_review_snapshot_integrity_report


LOCAL_CHECKS = {
    "django_migrations": "pass",
    "unit_tests": "pass",
    "sast_lint": "pass",
    "sca_dependencies": "pass",
    "secret_scan": "pass",
    "asvs_matrix": "pass",
    "owasp_api_matrix": "pass",
    "integrity_consolidated": "pass",
    "external_audit": "external_required",
    "postgres_object_restore": "external_required",
    "provider_outage": "external_required",
}

DEGRADED_MODES = {
    ResilienceExercise.Dependency.REDIS: "rate_limit_fail_closed",
    ResilienceExercise.Dependency.WORKER: "defer_noncritical_tasks",
    ResilienceExercise.Dependency.EXTERNAL_PROVIDER: "queue_no_external_retry",
    ResilienceExercise.Dependency.DATABASE: "reject_writes_fail_closed",
}


def _require_admin_or_security(*, user) -> None:
    if not (has_platform_permission(user=user, permission="platform.admin") or has_platform_permission(user=user, permission="security.review")):
        raise PermissionDenied("Un rôle sécurité ou administrateur est requis pour les contrôles de préparation.")


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def local_integrity_report() -> dict:
    """Agrège seulement les compteurs de contrôles locaux ; aucun dossier, secret ou fournisseur n’est exposé."""
    checks = {
        "audit_hmac": audit_integrity_report(),
        "evidence_artifacts": evidence_integrity_report(),
        "evidence_pipeline": evidence_pipeline_contract_report(),
        "external_service_registry": external_service_registry_integrity_report(),
        "privilege_review_snapshots": privilege_review_snapshot_integrity_report(),
        "report_scopes": report_scope_integrity_report(),
    }
    return {"checks": checks, "valid": all(check["valid"] for check in checks.values())}


def record_consolidated_integrity_snapshot(*, actor) -> ReadinessCheck:
    """Archive un verdict calculé localement, sans réparation ni appel de fournisseur."""
    report = local_integrity_report()
    return record_local_readiness_check(
        actor=actor,
        check_code="integrity_consolidated",
        status=ReadinessCheck.Status.PASS if report["valid"] else ReadinessCheck.Status.BLOCKED,
        evidence={
            "integrity_report": report,
            "calculated_locally": True,
            "external_service_called": False,
            "automatic_remediation_performed": False,
        },
    )


def readiness_check_integrity_report() -> dict:
    """Vérifie les digests append-only existants sans modifier les contrôles."""
    invalid_count = 0
    checked_count = 0
    for readiness_check in ReadinessCheck.objects.only("id", "evidence").iterator():
        checked_count += 1
        evidence = dict(readiness_check.evidence or {})
        recorded_digest = evidence.pop("evidence_digest", "")
        if not recorded_digest or recorded_digest != _digest(evidence):
            invalid_count += 1
    return {"checked_count": checked_count, "invalid_count": invalid_count, "valid": invalid_count == 0}


@transaction.atomic
def record_local_readiness_check(*, actor, check_code: str, status: str, evidence: dict) -> ReadinessCheck:
    _require_admin_or_security(user=actor)
    if check_code not in LOCAL_CHECKS or status not in ReadinessCheck.Status.values:
        raise ValidationError("Le contrôle ou son état ne fait pas partie du registre de préparation.")
    return ReadinessCheck.objects.create(check_code=check_code, status=status, evidence={**evidence, "evidence_digest": _digest(evidence)}, recorded_by=actor)


def verify_backup_restore_payload(*, backup_payload: dict, restored_payload: dict) -> dict:
    """Preuve locale de cohérence, sans sauvegarde PostgreSQL ni stockage objet réel."""
    source_digest = _digest(backup_payload)
    restored_digest = _digest(restored_payload)
    return {"source_digest": source_digest, "restored_digest": restored_digest, "matched": source_digest == restored_digest, "scope": "local-simulation-only"}


@transaction.atomic
def simulate_dependency_degradation(*, actor, dependency: str, operation: str, observed_mode: str | None = None) -> ResilienceExercise:
    _require_admin_or_security(user=actor)
    if dependency not in ResilienceExercise.Dependency.values or not operation.strip():
        raise ValidationError("La dépendance et l’opération sont obligatoires.")
    expected = DEGRADED_MODES[dependency]
    observed = observed_mode or expected
    return ResilienceExercise.objects.create(
        dependency=dependency,
        operation=operation.strip(),
        expected_mode=expected,
        observed_mode=observed,
        passed=observed == expected,
        evidence={"simulated": True, "at": timezone.now().isoformat(), "no_real_dependency_was_disabled": True},
    )


@transaction.atomic
def create_go_no_go_assessment(*, actor, local_evidence: dict, external_completed: bool = False) -> GoNoGoAssessment:
    _require_admin_or_security(user=actor)
    blockers = []
    if not external_completed:
        blockers.extend(["audit_externe_preproduction", "restauration_postgresql_objets", "tests_dependances_reelles", "decision_humaine_proprietaire"])
    return GoNoGoAssessment.objects.create(
        status="pending_human_decision",
        blockers=blockers,
        evidence={**local_evidence, "local_evidence_digest": _digest(local_evidence)},
    )
