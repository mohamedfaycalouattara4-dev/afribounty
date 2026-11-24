from django.core.exceptions import PermissionDenied

from django.db.models import Q

from apps.academy.models import Laboratory
from apps.academy.services import has_current_ethics_acceptance
from apps.identity.services import has_platform_permission
from apps.organizations.models import ConflictDeclaration, Organization, OrganizationMembership
from apps.programs.models import Program
from apps.readiness.models import GoNoGoAssessment, ReadinessCheck, ResilienceExercise
from apps.readiness.services import LOCAL_CHECKS, local_integrity_report
from apps.reputation.models import Challenge, ChallengeEnrollment, ReputationProfile, ReputationSeason
from apps.reports.models import Report, ReportDraft
from apps.reports.services import report_scope_integrity_report
from apps.reports.sla import sla_metrics_for_organization
from apps.rewards.models import BeneficiaryProfile, PaymentOrder, RewardEntitlement
from apps.security.audit import audit_integrity_report
from apps.security.privilege_review import privilege_review_snapshot, privilege_review_snapshot_integrity_report
from apps.security.models import PrivilegeReviewSnapshot


DESIGN_SYSTEM = {
    "language": "fr",
    "mobile_first": True,
    "contrast": "WCAG-AA-target",
    "components": ["navigation", "button", "form-field", "alert", "table", "empty-state"],
}

TRUST_PAGE_DEFAULTS = {
    "faq": ("FAQ", "Questions fréquentes sur la divulgation responsable, l’éligibilité et les capacités actuellement configurées."),
    "regles": ("Règles d’engagement", "Ne testez que les actifs explicitement autorisés, sans perturbation, collecte excessive ni contournement de contrôle."),
    "divulgation-responsable": (
        "Divulgation responsable",
        "Utilisez les canaux AfriBounty prévus, fournissez des informations minimales nécessaires et laissez le temps de traiter les signalements.",
    ),
    "conditions": (
        "Conditions d’utilisation",
        "L’accès est soumis au respect des règles, de la confidentialité et des lois applicables. "
        "Les intégrations externes ne sont activées qu’après validation opérationnelle.",
    ),
    "confidentialite": (
        "Politique de confidentialité",
        "Les préférences, demandes de droits et consentements sont tracés dans l’environnement actif. "
        "Aucun transfert externe n’est déclenché tant qu’un prestataire validé n’est pas configuré.",
    ),
}


def public_portal() -> dict:
    programs = Program.objects.filter(
        status=Program.Status.PUBLIC_ACTIVE,
        organization__verification_status=Organization.VerificationStatus.VERIFIED,
    ).values("id", "name", "policy_version")
    return {
        "design_system": DESIGN_SYSTEM,
        "programs": list(programs),
        "trust_pages": [{"slug": slug, "title": title} for slug, (title, _) in TRUST_PAGE_DEFAULTS.items()],
    }


def researcher_dashboard(*, user) -> dict:
    return {
        "reports": list(Report.objects.filter(author=user).values("id", "title", "status", "updated_at")),
        "drafts": list(ReportDraft.objects.filter(author=user).values("program_id", "program__name", "title", "updated_at")),
        "eligible_programs": list(
            Program.objects.filter(
                status=Program.Status.PUBLIC_ACTIVE,
                organization__verification_status="verified",
            ).values("id", "name", "policy_version")
        ),
        "reputation": list(
            user.reputation_profiles.select_related("season").order_by("-season__starts_at").values("season__code", "points", "rank", "recalculated_at")
        ),
        "access": {"academy_labs": has_current_ethics_acceptance(learner=user)},
    }


def organization_dashboard(*, user, organization) -> dict:
    membership = OrganizationMembership.objects.filter(organization=organization, user=user).first()
    if not membership or ConflictDeclaration.objects.filter(organization=organization, user=user, active=True).exists():
        raise PermissionDenied("Accès au tableau de bord organisation refusé.")
    can_message_reports = membership.role in {
        OrganizationMembership.Role.OWNER,
        OrganizationMembership.Role.PROGRAM_MANAGER,
        OrganizationMembership.Role.TRIAGER,
    }
    reports = []
    if can_message_reports:
        reports = [
            {
                "id": report.id,
                "title": report.title,
                "status": report.status,
                "status_label": report.get_status_display(),
                "program__name": report.program.name,
            }
            for report in organization.reports.select_related("program").order_by("created_at", "id")
        ]
    sla_metrics = sla_metrics_for_organization(organization=organization)
    return {
        "organization": organization.name,
        "organization_object": organization,
        "membership_role": membership.get_role_display(),
        "can_create_program": (
            organization.verification_status == Organization.VerificationStatus.VERIFIED
            and membership.role in {OrganizationMembership.Role.OWNER, OrganizationMembership.Role.PROGRAM_MANAGER}
        ),
        "programs": list(organization.programs.values("id", "name", "status")),
        "reports_total": organization.reports.count(),
        "can_message_reports": can_message_reports,
        "can_export_triage": membership.role == OrganizationMembership.Role.OWNER,
        "can_view_analytics": membership.role in {OrganizationMembership.Role.OWNER, OrganizationMembership.Role.PROGRAM_MANAGER},
        "can_view_audit": membership.role == OrganizationMembership.Role.OWNER,
        "reports": reports,
        "members": organization.memberships.count(),
        "sla_metrics": sla_metrics,
    }


def triage_console(*, user) -> dict:
    if not has_platform_permission(user=user, permission="report.triage"):
        raise PermissionDenied("Console de triage refusée.")
    reports = (
        Report.objects.filter(
            Q(status__in={Report.Status.SUBMITTED, Report.Status.IN_TRIAGE, Report.Status.INFORMATION_REQUIRED})
            | Q(status=Report.Status.VALID, triage_assignment__assigned_to=user)
        )
        .select_related("program", "triage_assignment__assigned_to")
        .order_by("created_at", "id")
    )
    return {
        "reports": [
            {
                "id": report.id,
                "title": report.title,
                "status": report.status,
                "status_label": report.get_status_display(),
                "program__name": report.program.name,
                "triage_assignment__assigned_to__email": getattr(report.triage_assignment.assigned_to, "email", None)
                if hasattr(report, "triage_assignment")
                else None,
                "triage_assignment__queue": report.triage_assignment.get_queue_display() if hasattr(report, "triage_assignment") else None,
            }
            for report in reports
        ]
    }


def finance_console(*, user) -> dict:
    if not has_platform_permission(user=user, permission="reward.approve"):
        raise PermissionDenied("Console finance refusée.")
    entitlements = (
        RewardEntitlement.objects.select_related("beneficiary", "proposed_by", "report")
        .prefetch_related("approvals", "ledger_entries")
        .order_by("created_at", "id")
    )
    rows = []
    for entitlement in entitlements:
        profile = BeneficiaryProfile.objects.filter(user=entitlement.beneficiary).first()
        payment_order = PaymentOrder.objects.filter(entitlement=entitlement).first()
        required_approvals = 2 if entitlement.amount_xof >= 100_000 else 1
        rows.append(
            {
                "entitlement": entitlement,
                "beneficiary_profile": profile,
                "payment_order": payment_order,
                "required_approvals": required_approvals,
                "approved_count": entitlement.approvals.filter(approved=True).count(),
                "can_approve": (
                    entitlement.status == RewardEntitlement.Status.PENDING
                    and entitlement.proposed_by_id != user.id
                    and not entitlement.approvals.filter(approver=user).exists()
                ),
                "can_verify_beneficiary": bool(
                    profile and profile.verification_status == BeneficiaryProfile.VerificationStatus.PENDING and profile.user_id != user.id
                ),
                "can_create_sandbox_order": bool(
                    entitlement.status == RewardEntitlement.Status.APPROVED
                    and profile
                    and profile.verification_status == BeneficiaryProfile.VerificationStatus.VERIFIED
                    and payment_order is None
                ),
            }
        )
    return {
        "entitlements": list(RewardEntitlement.objects.values("id", "amount_xof", "status")),
        "reward_rows": rows,
    }


def administration_console(*, user) -> dict:
    if not has_platform_permission(user=user, permission="platform.admin"):
        raise PermissionDenied("Console administrative refusée.")
    organizations = Organization.objects.order_by("verification_status", "created_at", "id").values(
        "id",
        "name",
        "verification_status",
        "created_at",
        "programs__id",
    )
    rows: dict[int, dict] = {}
    for organization in organizations:
        row = rows.setdefault(
            organization["id"],
            {
                "id": organization["id"],
                "name": organization["name"],
                "verification_status": organization["verification_status"],
                "created_at": organization["created_at"],
                "program_count": 0,
            },
        )
        if organization["programs__id"] is not None:
            row["program_count"] += 1
    draft_programs = (
        Program.objects.filter(status=Program.Status.DRAFT)
        .select_related("organization")
        .prefetch_related("scopes__ownership_proof", "policy_versions")
        .order_by("created_at", "id")
    )
    return {
        "organizations": list(rows.values()),
        "verification_statuses": Organization.VerificationStatus.choices,
        "draft_programs": draft_programs,
        **readiness_console(user=user),
    }


def readiness_console(*, user) -> dict:
    if not (has_platform_permission(user=user, permission="platform.admin") or has_platform_permission(user=user, permission="security.review")):
        raise PermissionDenied("Console de préparation refusée.")
    integrity_snapshot_history = []
    for snapshot in (
        ReadinessCheck.objects.filter(check_code="integrity_consolidated").only("created_at", "status", "evidence").order_by("-created_at", "-id")[:25]
    ):
        integrity_snapshot_history.append(
            {
                "created_at": snapshot.created_at,
                "status_label": snapshot.get_status_display(),
                "evidence_digest_prefix": str(snapshot.evidence.get("evidence_digest", ""))[:12],
            }
        )
    return {
        "readiness_checks": ReadinessCheck.objects.only("created_at", "check_code", "status").order_by("-created_at", "-id")[:25],
        "integrity_snapshot_history": integrity_snapshot_history,
        "resilience_exercises": ResilienceExercise.objects.order_by("-executed_at", "-id")[:25],
        "go_no_go_assessment": GoNoGoAssessment.objects.order_by("-created_at", "-id").first(),
        "local_readiness_codes": [(code, expected) for code, expected in LOCAL_CHECKS.items() if expected == "pass"],
        "resilience_dependencies": ResilienceExercise.Dependency.choices,
        "readiness_statuses": ReadinessCheck.Status.choices,
        "report_scope_integrity": report_scope_integrity_report(),
        "audit_integrity": audit_integrity_report(),
        "local_integrity": local_integrity_report(),
    }


def local_integrity_console(*, user) -> dict:
    if not (has_platform_permission(user=user, permission="platform.admin") or has_platform_permission(user=user, permission="security.review")):
        raise PermissionDenied("Console d’intégrité locale refusée.")
    integrity = local_integrity_report()
    checks = []
    for code, report in integrity["checks"].items():
        metrics = [f"{key.replace('_', ' ')} : {value}" for key, value in report.items() if key not in {"checked_count", "valid"}]
        checks.append(
            {
                "code": code,
                "checked_count": report["checked_count"],
                "valid": report["valid"],
                "metrics": " · ".join(metrics) or "Aucun écart détecté",
            }
        )
    return {"integrity": integrity, "integrity_checks": checks}


def privilege_review_console(*, user) -> dict:
    if not (has_platform_permission(user=user, permission="platform.admin") or has_platform_permission(user=user, permission="security.review")):
        raise PermissionDenied("Console de revue des privilèges refusée.")
    return {
        "snapshot": privilege_review_snapshot(),
        "privilege_review_history": PrivilegeReviewSnapshot.objects.order_by("-reviewed_at", "-id")[:25],
        "privilege_review_integrity": privilege_review_snapshot_integrity_report(),
    }


def academy_and_challenges(*, user) -> dict:
    has_ethics = has_current_ethics_acceptance(learner=user)
    eligible_challenges = Challenge.objects.filter(
        status__in=[Challenge.Status.OPEN, Challenge.Status.CLOSED],
        is_isolated=True,
        contains_external_target=False,
    ).order_by("starts_at", "id")
    enrollment_ids = set(ChallengeEnrollment.objects.filter(learner=user, challenge__in=eligible_challenges).values_list("challenge_id", flat=True))
    return {
        "laboratories": list(Laboratory.objects.filter(active=True).values("code", "title")) if has_ethics else [],
        "challenges": [
            {
                "code": challenge.code,
                "title": challenge.title,
                "status_label": challenge.get_status_display(),
                "starts_at": challenge.starts_at,
                "ends_at": challenge.ends_at,
                "enrolled": challenge.id in enrollment_ids,
            }
            for challenge in eligible_challenges
        ],
        "ethics_accepted": has_ethics,
    }


def researcher_reputation(*, user) -> dict:
    seasons = ReputationSeason.objects.order_by("-starts_at", "id")
    profiles = ReputationProfile.objects.filter(user=user).select_related("season").order_by("-season__starts_at", "id")
    return {
        "seasons": list(seasons),
        "profiles": list(profiles),
    }
