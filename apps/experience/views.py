import secrets

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count, Q
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.experience.services import (
    TRUST_PAGE_DEFAULTS,
    administration_console,
    academy_and_challenges,
    finance_console,
    local_integrity_console,
    organization_dashboard,
    privilege_review_console,
    public_portal,
    readiness_console,
    researcher_dashboard,
    researcher_reputation,
    triage_console,
)
from apps.academy.services import (
    CURRENT_ETHICS_RULES_TEXT,
    CURRENT_ETHICS_RULES_VERSION,
    accept_current_ethics,
    has_current_ethics_acceptance,
)
from apps.identity.models import (
    AccountDataRequest,
    AccountPrivacyPreference,
    AuthenticationEvent,
    RecoveryRequest,
    TotpDevice,
    User,
    UserSession,
    WebAuthnCredential,
)
from apps.identity.services import (
    cancel_account_data_right,
    has_platform_permission,
    request_account_data_right,
    request_recovery,
    require_step_up,
    revoke_session,
)
from apps.security.action_gate import assess_adaptive_action
from apps.integrations.local_notifications import create_local_notification, mark_local_notification_read
from apps.integrations.models import ApiKey, ApiKeyUsageEvent, ContentPage, LocalNotification, SupportCase
from apps.integrations.services import (
    create_api_key,
    open_support_case,
    publish_content,
    reply_to_support_case,
    rotate_api_key,
    revoke_api_key,
    set_notification_preference,
    set_support_case_status,
)
from apps.organizations.models import (
    ConflictDeclaration,
    Organization,
    OrganizationChangeEvent,
    OrganizationComplianceEvidence,
    OrganizationComplianceRequest,
    OrganizationMembership,
)
from apps.organizations.services import (
    add_security_contact,
    declare_conflict,
    delegate_membership,
    record_organization_change,
    require_organization_permission,
    set_verification_status,
)
from apps.programs.models import AssetScope, Program, ProgramInvitation, ProgramServiceLevel
from apps.programs.services import (
    add_program_draft_scope,
    create_program_draft,
    invite_private_program_researcher,
    publish_program_after_admin_review,
    revoke_private_program_invitation,
    review_program_scope,
    resume_program_emergency,
    suspend_program_emergency,
    update_program_service_level,
)
from apps.readiness.models import ReadinessCheck, ResilienceExercise
from apps.readiness.services import (
    LOCAL_CHECKS,
    create_go_no_go_assessment,
    record_consolidated_integrity_snapshot,
    record_local_readiness_check,
    simulate_dependency_degradation,
)
from apps.security.privilege_review import record_privilege_review_snapshot
from apps.reputation.models import Challenge, ChallengeEnrollment, ChallengeResult, ReputationProfile, ResearcherPublicProfile
from apps.reputation.services import (
    create_isolated_challenge,
    enroll_challenge,
    set_isolated_challenge_status,
    submit_challenge_result,
    validate_challenge_result,
)
from apps.reports.models import (
    FixValidation,
    MediationCase,
    RemediationTracking,
    Report,
    ReportDraft,
    ReportRelation,
    SeverityAssessment,
    TriageAssignment,
    TriageDecision,
)
from apps.reports.services import (
    add_report_evidence,
    get_report_conversation,
    list_report_evidence,
    save_report_draft,
    send_report_message,
    submit_report,
    transition_report,
)
from apps.reports.sla import sla_metrics_for_program
from apps.reports.triage import (
    assign_triage,
    decide_mediation,
    export_triage_aggregate,
    relate_reports,
    record_severity,
    record_triage_decision,
    request_mediation,
    start_remediation,
    submit_fix_for_validation,
    triage_metrics_for_program,
    validate_fix,
)
from apps.rewards.models import BeneficiaryProfile, LedgerEntry, ReconciliationReport, RewardEntitlement
from apps.rewards.sandbox import SandboxPaymentProvider
from apps.rewards.services import (
    approve_reward,
    cancel_reward,
    create_payment_order,
    create_reward_entitlement,
    reconcile_sandbox_payments,
    set_beneficiary_profile,
    verify_beneficiary,
)


LOCAL_SANDBOX_PAYMENT_SECRET = "afribounty-local-sandbox-no-network-secret"


def public_home(request):
    return render(request, "experience/home.html", public_portal())


def public_program_detail_view(request, program_id: int):
    program = get_object_or_404(
        Program.objects.select_related("organization").prefetch_related("policy_versions", "scopes"),
        pk=program_id,
        status=Program.Status.PUBLIC_ACTIVE,
        organization__verification_status="verified",
    )
    policy = program.policy_versions.filter(active=True).first()
    scopes = program.scopes.filter(is_active=True, is_verified=True, is_excluded=False).order_by("asset")
    return render(request, "experience/program_detail.html", {"program": program, "policy": policy, "scopes": scopes})


def public_program_catalog_view(request):
    query = request.GET.get("q", "").strip()
    asset_type = request.GET.get("asset_type", "").strip()
    programs = (
        Program.objects.filter(
            status=Program.Status.PUBLIC_ACTIVE,
            organization__verification_status=Organization.VerificationStatus.VERIFIED,
        )
        .select_related("organization")
        .prefetch_related("scopes")
    )
    if query:
        programs = programs.filter(Q(name__icontains=query) | Q(organization__name__icontains=query))
    if asset_type in AssetScope.AssetType.values:
        programs = programs.filter(scopes__asset_type=asset_type, scopes__is_active=True, scopes__is_verified=True, scopes__is_excluded=False).distinct()
    page_obj = Paginator(programs.order_by("name", "id"), 12).get_page(request.GET.get("page"))
    return render(
        request,
        "experience/program_catalog.html",
        {"page_obj": page_obj, "query": query, "asset_type": asset_type, "asset_types": AssetScope.AssetType.choices},
    )


def public_content_page_view(request, slug: str):
    page = ContentPage.objects.filter(slug=slug, published=True).first()
    if page:
        return render(request, "experience/content_page.html", {"page": page, "is_default": False})
    default = TRUST_PAGE_DEFAULTS.get(slug)
    if not default:
        return resource_not_found_view(request)
    return render(request, "experience/content_page.html", {"page": {"slug": slug, "title": default[0], "body": default[1]}, "is_default": True})


@login_required
@require_http_methods(["GET", "POST"])
def content_console_view(request):
    if not has_platform_permission(user=request.user, permission="platform.admin"):
        raise PermissionDenied("La console de contenus est réservée à l’administration.")
    if request.method == "POST":
        try:
            publish_content(
                actor=request.user,
                slug=request.POST.get("slug", ""),
                title=request.POST.get("title", ""),
                body=request.POST.get("body", ""),
                published=request.POST.get("published") == "on",
            )
        except (PermissionDenied, ValidationError) as exc:
            messages.error(request, " ".join(exc.messages) if hasattr(exc, "messages") else str(exc))
        else:
            messages.success(request, "La page est enregistrée dans la console locale. Sa publication reste limitée à cette instance.")
        return redirect("experience-content-console")
    return render(
        request,
        "experience/content_console.html",
        {"pages": ContentPage.objects.select_related("created_by").order_by("slug"), "defaults": TRUST_PAGE_DEFAULTS},
    )


@login_required
@require_http_methods(["GET", "POST"])
def api_key_console_view(request):
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "create":
                scopes = [scope.strip() for scope in request.POST.get("scopes", "").split(",") if scope.strip()]
                _, raw = create_api_key(
                    owner=request.user, label=request.POST.get("label", ""), scopes=scopes, ttl_days=int(request.POST.get("ttl_days", "30"))
                )
                request.session["api_key_reveal_once"] = raw
                messages.success(request, "La clé locale est créée. Son secret n’est affiché qu’une seule fois après cette redirection.")
            elif action == "rotate":
                key = get_object_or_404(ApiKey, pk=request.POST.get("key_id"), owner=request.user)
                _, raw = rotate_api_key(key=key, actor=request.user)
                request.session["api_key_reveal_once"] = raw
                messages.success(request, "La clé est tournée localement ; l’ancienne clé est révoquée.")
            elif action == "revoke":
                key = get_object_or_404(ApiKey, pk=request.POST.get("key_id"), owner=request.user, revoked_at__isnull=True)
                revoke_api_key(key=key, actor=request.user)
                messages.success(request, "La clé est révoquée dans cette instance locale.")
            else:
                raise ValidationError("Action API inconnue.")
        except (PermissionDenied, ValidationError, ValueError) as exc:
            messages.error(request, " ".join(exc.messages) if hasattr(exc, "messages") else str(exc))
        return redirect("experience-api-key-console")
    reveal_once = request.session.pop("api_key_reveal_once", None)
    return render(
        request,
        "experience/api_key_console.html",
        {
            "keys": ApiKey.objects.filter(owner=request.user).prefetch_related("usage_events").order_by("-created_at"),
            "reveal_once": reveal_once,
            "usage_events": ApiKeyUsageEvent.objects.filter(key__owner=request.user).select_related("key").order_by("-created_at")[:30],
            "api_key_creation_gate": assess_adaptive_action(user=request.user, action="api_key.create"),
        },
    )


def public_researcher_leaderboard_view(request):
    rankings = (
        ReputationProfile.objects.filter(season__active=True, user__public_researcher_profile__opted_in=True)
        .select_related("season", "user__public_researcher_profile")
        .order_by("season__code", "rank", "-points", "user_id")
    )
    return render(request, "experience/public_researcher_leaderboard.html", {"rankings": rankings})


@login_required
@require_http_methods(["GET", "POST"])
def researcher_public_profile_settings_view(request):
    if request.user.platform_role != User.PlatformRole.RESEARCHER:
        raise PermissionDenied("Le profil public est réservé aux comptes chercheurs.")
    profile, _ = ResearcherPublicProfile.objects.get_or_create(user=request.user, defaults={"public_alias": request.user.account_profile.display_name})
    if request.method == "POST":
        alias = request.POST.get("public_alias", "").strip()
        if not 3 <= len(alias) <= 80:
            messages.error(request, "L’alias public doit comporter entre 3 et 80 caractères.")
        else:
            profile.public_alias = alias
            profile.opted_in = request.POST.get("opted_in") == "on"
            profile.save(update_fields=["public_alias", "opted_in", "updated_at"])
            messages.success(request, "Votre choix de visibilité publique est enregistré localement.")
            return redirect("experience-researcher-public-profile-settings")
    return render(
        request,
        "experience/researcher_public_profile_settings.html",
        {"profile": profile, "calculated_profiles": ReputationProfile.objects.filter(user=request.user, season__active=True)},
    )


def access_required(request):
    return render(request, "experience/access_required.html", status=403)


@login_required
@require_http_methods(["GET", "POST"])
def notification_inbox_view(request):
    if request.method == "POST":
        action = request.POST.get("action", "read")
        if action == "read":
            notification_id = request.POST.get("notification_id")
            mark_local_notification_read(user=request.user, notification_id=int(notification_id) if notification_id else None)
            messages.success(request, "Les notifications sélectionnées sont marquées comme lues dans cette instance locale.")
        elif action == "archive":
            item = get_object_or_404(LocalNotification, pk=request.POST.get("notification_id"), user=request.user)
            item.archived_at = timezone.now()
            item.save(update_fields=["archived_at"])
            messages.success(request, "La notification est archivée localement.")
        elif action == "preferences":
            event_type = request.POST.get("event_type", "")
            set_notification_preference(
                user=request.user,
                event_type=event_type,
                channel="in_app",
                enabled=request.POST.get("enabled") == "on",
                max_per_day=int(request.POST.get("max_per_day", "5")),
                consented=True,
            )
            messages.success(request, "La préférence de notification locale est enregistrée.")
        return redirect("experience-notification-inbox")
    event_type = request.GET.get("type", "")
    include_archived = request.GET.get("archived") == "1"
    notifications = LocalNotification.objects.filter(user=request.user)
    if not include_archived:
        notifications = notifications.filter(archived_at__isnull=True)
    if event_type in LocalNotification.EventType.values:
        notifications = notifications.filter(event_type=event_type)
    return render(
        request,
        "experience/notification_inbox.html",
        {
            "notifications": notifications,
            "unread_count": notifications.filter(read_at__isnull=True).count(),
            "event_types": LocalNotification.EventType.choices,
            "selected_type": event_type,
            "preferences": request.user.notification_preferences.filter(channel="in_app"),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def support_center_view(request):
    if request.method == "POST":
        try:
            open_support_case(
                requester=request.user,
                subject=request.POST.get("subject", ""),
                message=request.POST.get("message", ""),
            )
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
        else:
            messages.success(request, "Votre ticket local est ouvert. N’ajoutez ni mot de passe, ni preuve, ni contenu d’exploitation.")
            return redirect("experience-support-center")
    cases = SupportCase.objects.filter(requester=request.user).prefetch_related("replies__author")
    return render(request, "experience/support_center.html", {"cases": cases})


@login_required
@require_http_methods(["GET", "POST"])
def support_console_view(request):
    can_review = has_platform_permission(user=request.user, permission="security.review") or has_platform_permission(
        user=request.user, permission="platform.admin"
    )
    if not can_review:
        raise PermissionDenied("La console support est réservée aux opérateurs autorisés.")
    if request.method == "POST":
        case = get_object_or_404(SupportCase, pk=request.POST.get("case_id"))
        try:
            if request.POST.get("status"):
                set_support_case_status(case=case, agent=request.user, status=request.POST["status"])
            if request.POST.get("reply", "").strip():
                reply_to_support_case(case=case, agent=request.user, message=request.POST["reply"])
        except (PermissionDenied, ValidationError) as exc:
            messages.error(request, " ".join(exc.messages) if hasattr(exc, "messages") else str(exc))
        else:
            messages.success(request, "Le ticket de support local est mis à jour.")
        return redirect("experience-support-console")
    cases = SupportCase.objects.select_related("requester").prefetch_related("replies__author")
    return render(request, "experience/support_console.html", {"cases": cases})


def permission_denied_view(request, exception=None):
    return render(request, "experience/permission_denied.html", status=403)


def resource_not_found_view(request, exception=None):
    return render(request, "experience/resource_not_found.html", status=404)


def _report_history(*, report: Report) -> list[dict]:
    labels = dict(Report.Status.choices)
    return [
        {
            "created_at": event.created_at,
            "status_label": labels.get(event.to_status, event.to_status or "Création"),
            "reason": event.reason,
        }
        for event in report.events.all()
    ]


@login_required
def researcher_onboarding(request):
    return render(request, "experience/onboarding.html", {"email_verified": request.user.email_verified})


@login_required
def researcher_dashboard_view(request):
    if request.user.platform_role != User.PlatformRole.RESEARCHER:
        raise PermissionDenied("Cet espace est réservé aux chercheurs en sécurité.")
    return render(request, "experience/researcher_dashboard.html", researcher_dashboard(user=request.user))


@login_required
def researcher_reputation_view(request):
    if request.user.platform_role != User.PlatformRole.RESEARCHER:
        raise PermissionDenied("Cet espace est réservé aux chercheurs en sécurité.")
    return render(request, "experience/researcher_reputation.html", researcher_reputation(user=request.user))


@login_required
@require_http_methods(["GET", "POST"])
def beneficiary_settings_view(request):
    if request.user.platform_role != User.PlatformRole.RESEARCHER:
        raise PermissionDenied("Les paramètres de bénéficiaire sont réservés aux chercheurs en sécurité.")
    profile = BeneficiaryProfile.objects.filter(user=request.user).first()
    try:
        require_step_up(user=request.user, action="beneficiary.change")
    except PermissionDenied:
        step_up_active = False
    else:
        step_up_active = True
    if request.method == "POST":
        try:
            profile = set_beneficiary_profile(
                user=request.user,
                provider_code="sandbox-money",
                recipient_reference=request.POST.get("recipient_reference", ""),
            )
        except (PermissionDenied, ValidationError) as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Le profil de bénéficiaire est enregistré et attend une vérification finance indépendante.")
            return redirect("experience-beneficiary-settings")
    return render(
        request,
        "experience/beneficiary_settings.html",
        {"profile": profile, "step_up_active": step_up_active},
    )


@login_required
@require_http_methods(["GET", "POST"])
def researcher_privacy_settings_view(request):
    if request.user.platform_role != User.PlatformRole.RESEARCHER:
        raise PermissionDenied("Les paramètres de confidentialité de compte sont réservés aux chercheurs en sécurité.")
    preference, _ = AccountPrivacyPreference.objects.get_or_create(user=request.user)
    if request.method == "POST":
        try:
            action = request.POST.get("action", "settings")
            if action == "settings":
                retention_days = int(request.POST.get("retention_days", "0"))
                if not 30 <= retention_days <= 3650:
                    raise ValidationError("La conservation doit être comprise entre 30 et 3 650 jours.")
                preference.retention_days = retention_days
                preference.exports_enabled = request.POST.get("exports_enabled") == "on"
                preference.save(update_fields=["retention_days", "exports_enabled", "updated_at"])
                messages.success(request, "Vos préférences de conservation et d’export local sont enregistrées.")
            elif action == "request_export":
                if not preference.exports_enabled:
                    raise ValidationError("Activez d’abord l’autorisation de préparation d’export local.")
                request_account_data_right(user=request.user, request_type=AccountDataRequest.RequestType.EXPORT)
                messages.success(request, "La demande d’export local est enregistrée. Aucun fichier ni e-mail n’est envoyé automatiquement.")
            elif action == "request_erasure":
                request_account_data_right(user=request.user, request_type=AccountDataRequest.RequestType.ERASURE)
                messages.success(request, "La demande d’effacement contrôlé est enregistrée. Aucune donnée n’est supprimée automatiquement.")
            elif action == "cancel_request":
                data_request = get_object_or_404(AccountDataRequest, pk=request.POST.get("request_id"), user=request.user)
                cancel_account_data_right(user=request.user, request=data_request)
                messages.success(request, "La demande locale en attente est annulée.")
            else:
                raise ValidationError("Action de confidentialité inconnue.")
        except (ValueError, ValidationError) as exc:
            messages.error(request, " ".join(exc.messages) if hasattr(exc, "messages") else str(exc))
        else:
            pass
        return redirect("experience-researcher-privacy-settings")
    return render(
        request,
        "experience/researcher_privacy_settings.html",
        {"preference": preference, "data_requests": request.user.data_rights_requests.order_by("-requested_at", "-id")},
    )


@login_required
@require_http_methods(["GET", "POST"])
def account_security_settings_view(request):
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "revoke_session":
                session = get_object_or_404(UserSession, pk=request.POST.get("session_id"), user=request.user, revoked_at__isnull=True)
                revoke_session(session=session)
                messages.success(request, "La session gérée sélectionnée est révoquée dans cette instance locale.")
            elif action == "request_recovery":
                request_recovery(user=request.user)
                messages.success(request, "La demande de récupération est enregistrée localement et attend une approbation ; aucun e-mail n’est envoyé.")
            else:
                raise ValidationError("Action de sécurité inconnue.")
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
        return redirect("experience-account-security-settings")
    return render(
        request,
        "experience/account_security_settings.html",
        {
            "sessions": UserSession.objects.filter(user=request.user).order_by("-created_at"),
            "totp_devices": TotpDevice.objects.filter(user=request.user).order_by("-created_at"),
            "webauthn_credentials": WebAuthnCredential.objects.filter(user=request.user).order_by("-created_at"),
            "recoveries": RecoveryRequest.objects.filter(user=request.user).order_by("-id"),
            "consents": request.user.consents.order_by("-accepted_at"),
            "authentication_events": AuthenticationEvent.objects.filter(user=request.user).order_by("-occurred_at")[:50],
        },
    )


@login_required
def challenge_detail_view(request, challenge_code: str):
    challenge = get_object_or_404(
        Challenge,
        code=challenge_code,
        status__in=[Challenge.Status.OPEN, Challenge.Status.CLOSED],
        is_isolated=True,
        contains_external_target=False,
    )
    enrollment = ChallengeEnrollment.objects.select_related("result").filter(challenge=challenge, learner=request.user).first()
    currently_open = challenge.status == Challenge.Status.OPEN and challenge.starts_at <= timezone.now() < challenge.ends_at
    return render(
        request,
        "experience/challenge_detail.html",
        {
            "challenge": challenge,
            "enrollment": enrollment,
            "result": getattr(enrollment, "result", None) if enrollment else None,
            "currently_open": currently_open,
            "can_enroll": bool(
                request.user.platform_role == User.PlatformRole.RESEARCHER and request.user.email_verified and currently_open and enrollment is None
            ),
        },
    )


@login_required
@require_http_methods(["POST"])
def challenge_enroll_view(request, challenge_code: str):
    if request.user.platform_role != User.PlatformRole.RESEARCHER:
        raise PermissionDenied("La participation aux challenges est réservée aux chercheurs en sécurité.")
    challenge = get_object_or_404(
        Challenge,
        code=challenge_code,
        status=Challenge.Status.OPEN,
        is_isolated=True,
        contains_external_target=False,
    )
    try:
        enrollment = enroll_challenge(challenge=challenge, learner=request.user)
    except (PermissionDenied, ValidationError) as exc:
        messages.error(request, str(exc))
    else:
        create_local_notification(
            user=request.user,
            event_type=LocalNotification.EventType.CHALLENGE,
            title="Participation locale enregistrée",
            body="Votre participation est limitée au challenge pédagogique isolé ; aucune cible externe n’est concernée.",
            safe_reference=f"challenge:{enrollment.challenge_id}",
            idempotency_key=f"challenge-enrollment:{enrollment.id}",
        )
        messages.success(request, f"Votre participation locale au challenge « {enrollment.challenge.title} » est enregistrée.")
    return redirect("experience-challenge-detail", challenge_code=challenge.code)


@login_required
@require_http_methods(["POST"])
def challenge_result_submit_view(request, challenge_code: str):
    challenge = get_object_or_404(Challenge, code=challenge_code, is_isolated=True, contains_external_target=False)
    enrollment = get_object_or_404(ChallengeEnrollment, challenge=challenge, learner=request.user)
    try:
        submit_challenge_result(
            enrollment=enrollment, learner=request.user, score=int(request.POST.get("score", "-1")), reference=request.POST.get("reference", "")
        )
    except (PermissionDenied, ValidationError, ValueError) as exc:
        messages.error(request, " ".join(exc.messages) if hasattr(exc, "messages") else str(exc))
    else:
        messages.success(request, "Votre score est enregistré pour revue locale. Aucun environnement externe n’est concerné.")
    return redirect("experience-challenge-detail", challenge_code=challenge.code)


@login_required
@require_http_methods(["GET", "POST"])
def challenge_admin_console_view(request):
    if not has_platform_permission(user=request.user, permission="platform.admin"):
        raise PermissionDenied("La gestion des challenges est réservée à l’administration.")
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "create":
                starts_at = parse_datetime(request.POST.get("starts_at", ""))
                ends_at = parse_datetime(request.POST.get("ends_at", ""))
                if starts_at is None or ends_at is None:
                    raise ValidationError("Les dates ISO de début et de fin sont obligatoires.")
                if timezone.is_naive(starts_at):
                    starts_at = timezone.make_aware(starts_at)
                if timezone.is_naive(ends_at):
                    ends_at = timezone.make_aware(ends_at)
                create_isolated_challenge(
                    administrator=request.user,
                    code=request.POST.get("code", ""),
                    title=request.POST.get("title", ""),
                    scenario=request.POST.get("scenario", ""),
                    rules_version=request.POST.get("rules_version", ""),
                    rules_hash=request.POST.get("rules_hash", ""),
                    starts_at=starts_at,
                    ends_at=ends_at,
                )
                messages.success(request, "Le challenge isolé est créé en brouillon.")
            elif action == "status":
                challenge = get_object_or_404(Challenge, pk=request.POST.get("challenge_id"))
                set_isolated_challenge_status(administrator=request.user, challenge=challenge, status=request.POST.get("status", ""))
                messages.success(request, "Le statut du challenge isolé est mis à jour.")
            elif action == "review":
                result = get_object_or_404(ChallengeResult, pk=request.POST.get("result_id"))
                validate_challenge_result(
                    result=result,
                    reviewer=request.user,
                    anti_cheat_cleared=request.POST.get("anti_cheat") == "cleared",
                    approved=request.POST.get("approved") == "yes",
                    reason=request.POST.get("reason", ""),
                )
                messages.success(request, "La revue locale du résultat est enregistrée.")
            else:
                raise ValidationError("Action challenge inconnue.")
        except (PermissionDenied, ValidationError) as exc:
            messages.error(request, " ".join(exc.messages) if hasattr(exc, "messages") else str(exc))
        return redirect("experience-challenge-admin-console")
    return render(
        request,
        "experience/challenge_admin_console.html",
        {
            "challenges": Challenge.objects.prefetch_related("enrollments__learner", "enrollments__result").order_by("-starts_at"),
            "pending_results": ChallengeResult.objects.select_related("enrollment__challenge", "enrollment__learner").filter(
                review_status=ChallengeResult.ReviewStatus.PENDING
            ),
        },
    )


def _assert_draft_access(*, user, program: Program) -> None:
    if user.platform_role != User.PlatformRole.RESEARCHER:
        raise PermissionDenied("La préparation et la soumission de rapports sont réservées aux chercheurs en sécurité.")
    if not has_current_ethics_acceptance(learner=user):
        raise PermissionDenied("L’acceptation horodatée des règles d’éthique est requise avant tout rapport.")
    if program.status == Program.Status.PUBLIC_ACTIVE and program.organization.verification_status == "verified":
        return
    invited = ProgramInvitation.objects.filter(
        program=program,
        researcher=user,
        accepted_at__isnull=False,
        rules_accepted_at__isnull=False,
        revoked_at__isnull=True,
    ).exists()
    if program.status != Program.Status.PRIVATE_ACTIVE or not invited or program.organization.verification_status != "verified":
        raise PermissionDenied("Le chercheur ne peut pas commencer un brouillon pour ce programme.")


@login_required
@require_http_methods(["GET", "POST"])
def report_draft_view(request, program_id: int):
    program = get_object_or_404(Program.objects.select_related("organization"), pk=program_id)
    _assert_draft_access(user=request.user, program=program)
    if request.method == "POST":
        draft = save_report_draft(
            organization=program.organization,
            program=program,
            author=request.user,
            title=request.POST.get("title", ""),
            asset=request.POST.get("asset", ""),
            impact=request.POST.get("impact", ""),
            reproduction=request.POST.get("reproduction", ""),
            proposed_severity=request.POST.get("proposed_severity", ""),
            vulnerability_category=request.POST.get("vulnerability_category", ""),
            cwe_reference=request.POST.get("cwe_reference", ""),
            affected_version=request.POST.get("affected_version", ""),
            environment_details=request.POST.get("environment_details", ""),
        )
        messages.success(request, "Brouillon enregistré. La soumission finale reste contrôlée par les validations serveur.")
        return redirect("experience-report-draft", program_id=draft.program_id)
    draft = ReportDraft.objects.filter(program=program, author=request.user).first()
    return render(request, "experience/report_draft.html", {"program": program, "draft": draft})


@login_required
@require_http_methods(["GET", "POST"])
def report_submit_review_view(request, program_id: int):
    program = get_object_or_404(Program.objects.select_related("organization"), pk=program_id)
    _assert_draft_access(user=request.user, program=program)
    draft = ReportDraft.objects.filter(program=program, author=request.user).first()
    if draft is None:
        messages.error(request, "Enregistrez d’abord un brouillon avant de préparer sa soumission.")
        return redirect("experience-report-draft", program_id=program.id)
    submission_key = request.POST.get("submission_key", "") or secrets.token_urlsafe(24)
    if request.method == "POST":
        if request.POST.get("confirmed_rules") != "on":
            messages.error(request, "Confirmez avoir relu les règles et le scope avant la soumission.")
        elif not all([draft.title.strip(), draft.asset.strip(), draft.impact.strip(), draft.reproduction.strip()]):
            messages.error(request, "Le titre, l’actif, l’impact et les étapes de reproduction sont obligatoires avant la soumission.")
        else:
            result = submit_report(
                organization=program.organization,
                program=program,
                author=request.user,
                title=draft.title,
                asset=draft.asset,
                impact=draft.impact,
                reproduction=draft.reproduction,
                proposed_severity=draft.proposed_severity,
                vulnerability_category=draft.vulnerability_category,
                cwe_reference=draft.cwe_reference,
                affected_version=draft.affected_version,
                environment_details=draft.environment_details,
                idempotency_key=submission_key,
            )
            if result.was_created:
                create_local_notification(
                    user=request.user,
                    event_type=LocalNotification.EventType.REPORT,
                    title="Rapport transmis à la file locale",
                    body="Votre rapport a été enregistré avec l’état initial Soumis. Aucun contenu de rapport n’est affiché dans cette notification.",
                    safe_reference=f"report:{result.report.id}",
                    idempotency_key=f"report-submitted:{result.report.id}",
                )
                messages.success(request, "Le rapport a été soumis. Son état initial est « Soumis ».")
            else:
                messages.info(request, "Cette soumission a déjà été traitée ; aucun rapport en double n’a été créé.")
            return redirect("experience-report-detail", report_id=result.report.id)
    return render(request, "experience/report_submit_review.html", {"program": program, "draft": draft, "submission_key": submission_key})


@login_required
def report_detail_view(request, report_id: int):
    report = Report.objects.select_related("program", "organization").prefetch_related("events").filter(pk=report_id, author=request.user).first()
    if report is None:
        return resource_not_found_view(request)
    conversation = get_report_conversation(report=report, actor=request.user)
    mediation = MediationCase.objects.filter(report=report).select_related("initial_decider", "mediator", "independent_reviewer").first()
    return render(
        request,
        "experience/report_detail.html",
        {
            "report": report,
            "report_history": _report_history(report=report),
            "conversation_messages": conversation.messages.all() if conversation else [],
            "message_action": "experience-report-conversation-message-add",
            "message_key": secrets.token_urlsafe(24),
            "mediation": mediation,
            "can_request_mediation": bool(getattr(report, "triage_decision", None) and mediation is None),
            "evidence_items": list_report_evidence(report=report, actor=request.user),
            "evidence_key": secrets.token_urlsafe(24),
        },
    )


@login_required
@require_http_methods(["POST"])
def report_mediation_request_view(request, report_id: int):
    report = Report.objects.select_related("organization", "program", "triage_decision").filter(pk=report_id, author=request.user).first()
    if report is None:
        return resource_not_found_view(request)
    if MediationCase.objects.filter(report=report).exists():
        messages.info(request, "Une médiation est déjà ouverte pour ce rapport.")
    else:
        try:
            request_mediation(report=report, requester=request.user, reason=request.POST.get("reason", ""))
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
        else:
            messages.success(request, "La demande de médiation est enregistrée pour une revue séparée.")
    return redirect("experience-report-detail", report_id=report.id)


@login_required
@require_http_methods(["POST"])
def report_conversation_message_add_view(request, report_id: int):
    report = Report.objects.select_related("organization").filter(pk=report_id, author=request.user).first()
    if report is None:
        return resource_not_found_view(request)
    try:
        result = send_report_message(
            report=report,
            actor=request.user,
            body=request.POST.get("body", ""),
            idempotency_key=request.POST.get("message_key", ""),
        )
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(
            request,
            "Le message est enregistré dans le fil privé du rapport." if result.was_created else "Ce message a déjà été traité ; aucun doublon n’a été créé.",
        )
    return redirect("experience-report-detail", report_id=report.id)


@login_required
@require_http_methods(["POST"])
def report_evidence_add_view(request, report_id: int):
    report = Report.objects.select_related("organization").filter(pk=report_id, author=request.user).first()
    if report is None:
        return resource_not_found_view(request)
    try:
        result = add_report_evidence(
            report=report,
            actor=request.user,
            uploaded_file=request.FILES.get("evidence_file"),
            category=request.POST.get("category", "reproduction"),
            idempotency_key=request.POST.get("evidence_key", ""),
        )
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, "La preuve locale est enregistrée avec son empreinte." if result.was_created else "Cette preuve a déjà été traitée.")
    return redirect("experience-report-detail", report_id=report.id)


def _organization_report_or_404(*, request, organization_id: int, report_id: int) -> Report | None:
    report = Report.objects.select_related("organization", "program").prefetch_related("events").filter(pk=report_id, organization_id=organization_id).first()
    if report is None:
        return None
    try:
        get_report_conversation(report=report, actor=request.user)
    except PermissionDenied:
        return None
    return report


@login_required
def organization_report_detail_view(request, organization_id: int, report_id: int):
    report = _organization_report_or_404(request=request, organization_id=organization_id, report_id=report_id)
    if report is None:
        return resource_not_found_view(request)
    conversation = get_report_conversation(report=report, actor=request.user)
    remediation = RemediationTracking.objects.filter(report=report).select_related("owner").first()
    return render(
        request,
        "experience/report_detail.html",
        {
            "report": report,
            "report_history": _report_history(report=report),
            "organization_context": True,
            "organization_id": organization_id,
            "conversation_messages": conversation.messages.all() if conversation else [],
            "message_action": "experience-organization-report-conversation-message-add",
            "message_key": secrets.token_urlsafe(24),
            "remediation": remediation,
            "can_submit_fix": bool(
                remediation
                and remediation.owner_id == request.user.id
                and remediation.status
                in {
                    RemediationTracking.Status.PLANNED,
                    RemediationTracking.Status.IN_PROGRESS,
                    RemediationTracking.Status.REJECTED,
                }
            ),
            "evidence_items": list_report_evidence(report=report, actor=request.user),
            "evidence_key": secrets.token_urlsafe(24),
        },
    )


@login_required
@require_http_methods(["POST"])
def organization_remediation_submit_view(request, organization_id: int, report_id: int):
    report = _organization_report_or_404(request=request, organization_id=organization_id, report_id=report_id)
    if report is None:
        return resource_not_found_view(request)
    remediation = RemediationTracking.objects.filter(report=report).first()
    if remediation is None:
        return resource_not_found_view(request)
    try:
        submit_fix_for_validation(remediation=remediation, actor=request.user)
    except (PermissionDenied, ValidationError) as exc:
        messages.error(request, " ".join(exc.messages) if hasattr(exc, "messages") else str(exc))
    else:
        messages.success(request, "La correction est soumise à une validation indépendante dans l’instance locale.")
    return redirect("experience-organization-report-detail", organization_id=organization_id, report_id=report.id)


@login_required
@require_http_methods(["POST"])
def organization_report_conversation_message_add_view(request, organization_id: int, report_id: int):
    report = _organization_report_or_404(request=request, organization_id=organization_id, report_id=report_id)
    if report is None:
        return resource_not_found_view(request)
    try:
        result = send_report_message(
            report=report,
            actor=request.user,
            body=request.POST.get("body", ""),
            idempotency_key=request.POST.get("message_key", ""),
        )
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(
            request,
            "Le message de l’organisation est enregistré dans le fil privé."
            if result.was_created
            else "Ce message a déjà été traité ; aucun doublon n’a été créé.",
        )
    return redirect("experience-organization-report-detail", organization_id=organization_id, report_id=report.id)


@login_required
@require_http_methods(["POST"])
def organization_report_evidence_add_view(request, organization_id: int, report_id: int):
    report = _organization_report_or_404(request=request, organization_id=organization_id, report_id=report_id)
    if report is None:
        return resource_not_found_view(request)
    try:
        result = add_report_evidence(
            report=report,
            actor=request.user,
            uploaded_file=request.FILES.get("evidence_file"),
            category=request.POST.get("category", "remediation"),
            idempotency_key=request.POST.get("evidence_key", ""),
        )
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, "La preuve locale est enregistrée avec son empreinte." if result.was_created else "Cette preuve a déjà été traitée.")
    return redirect("experience-organization-report-detail", organization_id=organization_id, report_id=report.id)


@login_required
def organization_dashboard_view(request, organization_id: int):
    organization = get_object_or_404(Organization, pk=organization_id)
    return render(request, "experience/organization_dashboard.html", organization_dashboard(user=request.user, organization=organization))


@login_required
def organization_audit_log_view(request, organization_id: int):
    organization = get_object_or_404(Organization, pk=organization_id)
    require_organization_permission(user=request.user, organization=organization, permission="settings.manage")
    events = OrganizationChangeEvent.objects.filter(organization=organization).select_related("actor").order_by("-created_at", "-id")[:200]
    return render(
        request,
        "experience/organization_audit_log.html",
        {"organization": organization, "events": events},
    )


@login_required
def organization_analytics_view(request, organization_id: int):
    organization = get_object_or_404(Organization, pk=organization_id)
    require_organization_permission(user=request.user, organization=organization, permission="program.manage")
    status_rows = list(organization.reports.values("status").annotate(total=Count("id")).order_by("status"))
    status_labels = dict(Report.Status.choices)
    for row in status_rows:
        row["label"] = status_labels.get(row["status"], row["status"])
    program_rows = list(
        organization.programs.annotate(
            reports_total=Count("reports", distinct=True),
            remediation_total=Count("reports__remediation", distinct=True),
            resolved_total=Count("reports", filter=Q(reports__status=Report.Status.RESOLVED), distinct=True),
        )
        .values("id", "name", "reports_total", "remediation_total", "resolved_total")
        .order_by("name", "id")
    )
    remediation_total = RemediationTracking.objects.filter(report__organization=organization).count()
    remediation_verified = RemediationTracking.objects.filter(
        report__organization=organization,
        status=RemediationTracking.Status.VERIFIED,
    ).count()
    return render(
        request,
        "experience/organization_analytics.html",
        {
            "organization": organization,
            "status_rows": status_rows,
            "program_rows": program_rows,
            "reports_total": organization.reports.count(),
            "decisions_total": TriageDecision.objects.filter(report__organization=organization).count(),
            "remediation_total": remediation_total,
            "remediation_verified": remediation_verified,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def organization_triage_metrics_view(request, organization_id: int):
    organization = get_object_or_404(Organization, pk=organization_id)
    require_organization_permission(user=request.user, organization=organization, permission="export.request")
    programs = list(Program.objects.filter(organization=organization).order_by("name", "id"))
    selected_program_id = request.POST.get("program_id") if request.method == "POST" else request.GET.get("program_id")
    selected_program = None
    if selected_program_id:
        selected_program = get_object_or_404(Program, pk=selected_program_id, organization=organization)
    elif programs:
        selected_program = programs[0]
    metrics = triage_metrics_for_program(program=selected_program) if selected_program else None
    sla_metrics = sla_metrics_for_program(program=selected_program) if selected_program else None
    export_payload = None
    if request.method == "POST":
        if selected_program is None:
            messages.error(request, "Sélectionnez un programme de cette organisation avant l’export.")
        else:
            try:
                export_payload = export_triage_aggregate(
                    organization=organization,
                    program=selected_program,
                    actor=request.user,
                )
            except PermissionDenied as exc:
                messages.error(request, str(exc))
            else:
                messages.success(request, "L’export agrégé a été enregistré dans le journal organisationnel local.")
    return render(
        request,
        "experience/organization_triage_metrics.html",
        {
            "organization": organization,
            "programs": programs,
            "selected_program": selected_program,
            "metrics": metrics,
            "sla_metrics": sla_metrics,
            "export_payload": export_payload,
        },
    )


@login_required
def organization_program_detail_view(request, organization_id: int, program_id: int):
    organization = get_object_or_404(Organization, pk=organization_id)
    context = organization_dashboard(user=request.user, organization=organization)
    program = get_object_or_404(
        Program.objects.select_related("organization", "service_level").prefetch_related("policy_versions", "scopes"),
        pk=program_id,
        organization=organization,
    )
    policy = program.policy_versions.order_by("-created_at").first()
    try:
        service_level = program.service_level
    except ProgramServiceLevel.DoesNotExist:
        service_level = None
    event_labels = {
        "scope.verified": "Scope vérifié",
        "program.published_after_review": "Programme publié après revue",
        "program.service_level_updated": "Objectifs SLA mis à jour",
        "program.emergency_closed": "Programme suspendu en urgence",
        "program.emergency_resumed": "Programme repris après suspension",
    }
    program_events = []
    if context["can_create_program"]:
        for event in program.decision_events.select_related("actor").order_by("-created_at", "-id")[:50]:
            summary = "Événement de gouvernance enregistré."
            if event.action == "program.service_level_updated":
                current = event.metadata.get("current", {})
                summary = (
                    f"Accusé {current.get('acknowledgement_hours', '—')} h · "
                    f"triage {current.get('triage_hours', '—')} h · "
                    f"résolution {current.get('resolution_target_days', '—')} jours."
                )
            elif event.action == "scope.verified":
                summary = "Le scope a reçu une preuve de propriété approuvée."
            elif event.action == "program.published_after_review":
                summary = f"Politique {event.metadata.get('policy_version', '—')} validée pour publication."
            elif event.action == "program.emergency_closed":
                summary = "Le programme a été suspendu ; les accès chercheurs et les soumissions sont bloqués."
            elif event.action == "program.emergency_resumed":
                summary = f"Le programme a repris son état {event.metadata.get('restored_status', 'antérieur')}."
            program_events.append(
                {
                    "created_at": event.created_at,
                    "actor": getattr(event.actor, "email", "Compte retiré"),
                    "label": event_labels.get(event.action, "Événement de programme"),
                    "summary": summary,
                }
            )
    context.update(
        {
            "program": program,
            "policy": policy,
            "scopes": program.scopes.order_by("asset"),
            "service_level": service_level,
            "sla_metrics": sla_metrics_for_program(program=program),
            "program_events": program_events,
        }
    )
    return render(request, "experience/organization_program_detail.html", context)


@login_required
@require_http_methods(["POST"])
def organization_program_service_level_update_view(request, organization_id: int, program_id: int):
    organization = get_object_or_404(Organization, pk=organization_id)
    program = get_object_or_404(Program, pk=program_id, organization=organization)
    require_organization_permission(user=request.user, organization=organization, permission="program.manage")
    try:
        update_program_service_level(
            actor=request.user,
            organization=organization,
            program=program,
            acknowledgement_hours=request.POST.get("acknowledgement_hours", ""),
            triage_hours=request.POST.get("triage_hours", ""),
            resolution_target_days=request.POST.get("resolution_target_days", ""),
        )
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, "Les objectifs SLA sont mis à jour, recalculés localement et journalisés.")
    return redirect("experience-organization-program-detail", organization_id=organization.id, program_id=program.id)


@login_required
@require_http_methods(["POST"])
def organization_program_emergency_control_view(request, organization_id: int, program_id: int):
    organization = get_object_or_404(Organization, pk=organization_id)
    program = get_object_or_404(Program, pk=program_id, organization=organization)
    require_organization_permission(user=request.user, organization=organization, permission="settings.manage")
    action = request.POST.get("action", "")
    try:
        if action == "suspend":
            suspend_program_emergency(
                actor=request.user,
                organization=organization,
                program=program,
                reason=request.POST.get("reason", ""),
            )
            messages.success(request, "Le programme est suspendu localement : les accès chercheurs et les soumissions sont bloqués.")
        elif action == "resume":
            resume_program_emergency(
                actor=request.user,
                organization=organization,
                program=program,
                reason=request.POST.get("reason", ""),
            )
            messages.success(request, "Le programme a repris son état antérieur après confirmation MFA et journalisation.")
        else:
            raise ValidationError("Action d’urgence inconnue.")
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    return redirect("experience-organization-program-detail", organization_id=organization.id, program_id=program.id)


@login_required
@require_http_methods(["GET", "POST"])
def organization_program_invitations_view(request, organization_id: int, program_id: int):
    organization = get_object_or_404(Organization, pk=organization_id)
    program = get_object_or_404(Program, pk=program_id, organization=organization)
    require_organization_permission(user=request.user, organization=organization, permission="program.manage")
    if request.method == "POST":
        try:
            if request.POST.get("action") == "invite":
                researcher = User.objects.filter(email__iexact=request.POST.get("researcher_email", "").strip()).first()
                if researcher is None:
                    raise ValidationError("Aucun compte chercheur vérifié ne correspond à cette adresse e-mail.")
                invite_private_program_researcher(actor=request.user, organization=organization, program=program, researcher=researcher)
                messages.success(request, "L’invitation privée est enregistrée localement. Aucun e-mail ou message externe n’est envoyé.")
            elif request.POST.get("action") == "revoke":
                invitation = get_object_or_404(ProgramInvitation, pk=request.POST.get("invitation_id"), program=program)
                revoke_private_program_invitation(actor=request.user, organization=organization, invitation=invitation)
                messages.success(request, "L’invitation est révoquée dans cette instance locale.")
            else:
                raise ValidationError("Action d’invitation inconnue.")
        except (PermissionDenied, ValidationError) as exc:
            messages.error(request, " ".join(exc.messages) if hasattr(exc, "messages") else str(exc))
        return redirect("experience-organization-program-invitations", organization_id=organization.id, program_id=program.id)
    return render(
        request,
        "experience/organization_program_invitations.html",
        {"organization": organization, "program": program, "invitations": program.invitations.select_related("researcher").order_by("researcher__email")},
    )


@login_required
@require_http_methods(["POST"])
def organization_program_draft_scope_add_view(request, organization_id: int, program_id: int):
    organization = get_object_or_404(Organization, pk=organization_id)
    program = get_object_or_404(Program, pk=program_id, organization=organization)
    try:
        scope = add_program_draft_scope(
            user=request.user,
            organization=organization,
            program=program,
            asset=request.POST.get("asset", ""),
            asset_type=request.POST.get("asset_type", ""),
        )
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, f"Le scope « {scope.asset} » est ajouté comme non vérifié et reste interne.")
    return redirect("experience-organization-program-detail", organization_id=organization.id, program_id=program.id)


@login_required
@require_http_methods(["GET", "POST"])
def organization_program_draft_create_view(request, organization_id: int):
    organization = get_object_or_404(Organization, pk=organization_id)
    require_organization_permission(user=request.user, organization=organization, permission="program.manage")
    if organization.verification_status != Organization.VerificationStatus.VERIFIED:
        raise PermissionDenied("La vérification de l’organisation est requise avant l’accès à la création de programme.")
    if request.method == "POST":
        try:
            program = create_program_draft(
                user=request.user,
                organization=organization,
                name=request.POST.get("name", ""),
                asset=request.POST.get("asset", ""),
                asset_type=request.POST.get("asset_type", ""),
                safe_harbor_text=request.POST.get("safe_harbor_text", ""),
                acknowledgement_hours=int(request.POST.get("acknowledgement_hours", "0")),
                triage_hours=int(request.POST.get("triage_hours", "0")),
                resolution_target_days=int(request.POST.get("resolution_target_days", "0")),
            )
        except (ValueError, ValidationError) as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, f"Le brouillon « {program.name} » a été créé. Il reste non public et son scope doit être vérifié.")
            return redirect("experience-organization-dashboard", organization_id=organization.id)
    return render(
        request,
        "experience/program_draft_create.html",
        {"organization": organization, "asset_types": AssetScope.AssetType.choices},
    )


@login_required
@require_http_methods(["GET", "POST"])
def organization_settings_view(request, organization_id: int):
    organization = get_object_or_404(Organization, pk=organization_id)
    require_organization_permission(user=request.user, organization=organization, permission="settings.manage")
    if request.method == "POST":
        action = request.POST.get("action", "organization")
        try:
            if action == "organization":
                name = request.POST.get("name", "").strip()
                if len(name) < 3:
                    raise ValidationError("Le nom de l’organisation doit comporter au moins trois caractères.")
                organization.name = name
                organization.save(update_fields=["name"])
                record_organization_change(organization=organization, actor=request.user, action="organization.settings_updated")
                messages.success(request, "Les paramètres de l’organisation ont été enregistrés.")
            elif action == "privacy":
                retention_days = int(request.POST.get("privacy_retention_days", "0"))
                if not 30 <= retention_days <= 3650:
                    raise ValidationError("La conservation doit être comprise entre 30 et 3 650 jours.")
                organization.privacy_retention_days = retention_days
                organization.exports_enabled = request.POST.get("exports_enabled") == "on"
                organization.save(update_fields=["privacy_retention_days", "exports_enabled"])
                record_organization_change(
                    organization=organization,
                    actor=request.user,
                    action="organization.privacy_updated",
                    metadata={"retention_days": retention_days, "exports_enabled": organization.exports_enabled},
                )
                messages.success(request, "Les paramètres de conservation et d’export de l’organisation sont enregistrés.")
            elif action == "member":
                email = request.POST.get("member_email", "").strip().lower()
                role = request.POST.get("member_role", "")
                target_user = User.objects.filter(email=email, email_verified=True).first()
                if target_user is None:
                    raise ValidationError("Le compte invité doit déjà exister et avoir un e-mail vérifié.")
                if role not in dict(OrganizationMembership.Role.choices):
                    raise ValidationError("Le rôle organisationnel sélectionné est invalide.")
                membership = delegate_membership(actor=request.user, target_user=target_user, organization=organization, role=role)
                messages.success(request, f"Le rôle « {membership.get_role_display()} » est enregistré pour {target_user.email}.")
            elif action == "contact":
                contact = add_security_contact(
                    actor=request.user,
                    organization=organization,
                    label=request.POST.get("contact_label", ""),
                    email=request.POST.get("contact_email", ""),
                    emergency=request.POST.get("contact_emergency") == "on",
                )
                messages.success(request, f"Le contact de sécurité « {contact.label} » est enregistré.")
            elif action == "conflict":
                target_user = get_object_or_404(User, pk=request.POST.get("conflict_user_id", ""))
                declare_conflict(
                    actor=request.user,
                    organization=organization,
                    target_user=target_user,
                    reason=request.POST.get("conflict_reason", ""),
                )
                messages.success(request, f"Le conflit d’intérêt actif de {target_user.email} est enregistré.")
            else:
                raise ValidationError("Action de paramétrage inconnue.")
        except (PermissionDenied, ValidationError) as exc:
            messages.error(request, " ".join(exc.messages) if hasattr(exc, "messages") else str(exc))
        return redirect("experience-organization-settings", organization_id=organization.id)
    return render(
        request,
        "experience/organization_settings.html",
        {
            "organization": organization,
            "memberships": organization.memberships.select_related("user").order_by("role", "user__email"),
            "security_contacts": organization.security_contacts.order_by("label", "id"),
            "conflicts": ConflictDeclaration.objects.filter(organization=organization, active=True).select_related("user").order_by("user__email"),
            "membership_roles": OrganizationMembership.Role.choices,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def organization_compliance_view(request, organization_id: int):
    organization = get_object_or_404(Organization, pk=organization_id)
    require_organization_permission(user=request.user, organization=organization, permission="settings.manage")
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "evidence":
            label = request.POST.get("label", "").strip()
            reference = request.POST.get("local_reference", "").strip()
            if not label or not reference:
                messages.error(request, "Le libellé et la référence locale sont obligatoires.")
            else:
                OrganizationComplianceEvidence.objects.create(organization=organization, submitted_by=request.user, label=label, local_reference=reference)
                record_organization_change(organization=organization, actor=request.user, action="compliance.evidence_submitted", metadata={"label": label})
                messages.success(request, "La référence de preuve est enregistrée localement.")
        elif action == "request":
            message = request.POST.get("message", "").strip()
            if not message:
                messages.error(request, "La demande de complément doit être motivée.")
            else:
                OrganizationComplianceRequest.objects.create(organization=organization, requested_by=request.user, message=message)
                record_organization_change(organization=organization, actor=request.user, action="compliance.followup_requested")
                messages.success(request, "La demande de complément est enregistrée localement.")
        return redirect("experience-organization-compliance", organization_id=organization.id)
    return render(
        request,
        "experience/organization_compliance.html",
        {
            "organization": organization,
            "verification": getattr(organization, "verification", None),
            "evidence": organization.compliance_evidence.select_related("submitted_by").order_by("-created_at"),
            "requests": organization.compliance_requests.select_related("requested_by").order_by("-created_at"),
        },
    )


@login_required
def triage_console_view(request):
    return render(request, "experience/triage_console.html", triage_console(user=request.user))


def _triage_report_for_request(*, request, report_id: int):
    if not has_platform_permission(user=request.user, permission="report.triage"):
        raise PermissionDenied("Console de triage refusée.")
    report = (
        Report.objects.select_related("organization", "program", "author", "triage_assignment__assigned_to")
        .prefetch_related("events", "severity_assessments", "triage_events__actor")
        .filter(pk=report_id)
        .first()
    )
    return report


def _triage_assignment_for(*, report: Report):
    return TriageAssignment.objects.filter(report=report).select_related("assigned_to").first()


def _require_current_triage_assignee(*, request, report: Report):
    assignment = _triage_assignment_for(report=report)
    if assignment is None or assignment.assigned_to_id != request.user.id:
        raise PermissionDenied("Ce rapport doit être attribué à votre compte de triage avant toute décision.")
    return assignment


@login_required
@require_http_methods(["GET", "POST"])
def triage_report_detail_view(request, report_id: int):
    report = _triage_report_for_request(request=request, report_id=report_id)
    if report is None:
        return resource_not_found_view(request)

    if request.method == "POST":
        action = request.POST.get("action", "")
        try:
            assignment = _triage_assignment_for(report=report)
            if action == "claim":
                if assignment and assignment.assigned_to_id != request.user.id:
                    raise ValidationError("Ce rapport est déjà attribué à un autre membre du triage.")
                queue = request.POST.get("queue", TriageAssignment.Queue.PRE_TRIAGE)
                if queue not in dict(TriageAssignment.Queue.choices):
                    raise ValidationError("La file de triage sélectionnée est invalide.")
                assign_triage(
                    report=report,
                    actor=request.user,
                    assignee=request.user,
                    queue=queue,
                    reason=request.POST.get("reason", ""),
                )
                messages.success(request, "Le rapport vous est attribué et est placé dans la file de triage.")
            elif action == "severity":
                _require_current_triage_assignee(request=request, report=report)
                technical_severity = request.POST.get("technical_severity", "")
                if technical_severity not in dict(SeverityAssessment.TechnicalSeverity.choices):
                    raise ValidationError("La sévérité technique sélectionnée est invalide.")
                assessment = record_severity(
                    report=report,
                    evaluator=request.user,
                    technical_severity=technical_severity,
                    scoring_vector=request.POST.get("scoring_vector", ""),
                    justification=request.POST.get("justification", ""),
                )
                messages.success(request, f"Évaluation de sévérité v{assessment.version} enregistrée.")
            elif action == "decision":
                _require_current_triage_assignee(request=request, report=report)
                priority = request.POST.get("business_priority", "")
                eligibility = request.POST.get("reward_eligibility", "")
                if priority not in dict(TriageDecision.BusinessPriority.choices):
                    raise ValidationError("La priorité métier sélectionnée est invalide.")
                if eligibility not in dict(TriageDecision.RewardEligibility.choices):
                    raise ValidationError("Le statut d’éligibilité sélectionné est invalide.")
                decision = record_triage_decision(
                    report=report,
                    decider=request.user,
                    business_priority=priority,
                    reward_eligibility=eligibility,
                    justification=request.POST.get("justification", ""),
                    reason_code=request.POST.get("reason_code", TriageDecision.ReasonCode.PENDING),
                )
                create_local_notification(
                    user=report.author,
                    event_type=LocalNotification.EventType.TRIAGE,
                    title="Décision de triage enregistrée",
                    body="Une décision de triage a été enregistrée pour votre rapport. Consultez la fiche privée du rapport pour les éléments autorisés.",
                    safe_reference=f"report:{report.id}",
                    idempotency_key=f"triage-decision:{decision.id}",
                )
                messages.success(request, "Décision de priorité et d’éligibilité enregistrée.")
            elif action == "transition":
                _require_current_triage_assignee(request=request, report=report)
                target_status = request.POST.get("target_status", "")
                allowed_targets = {
                    Report.Status.INFORMATION_REQUIRED,
                    Report.Status.VALID,
                    Report.Status.OUT_OF_SCOPE,
                    Report.Status.NON_REPRODUCIBLE,
                }
                if target_status not in allowed_targets:
                    raise ValidationError("La transition sélectionnée n’est pas disponible depuis cette fiche.")
                if not SeverityAssessment.objects.filter(report=report).exists() or not TriageDecision.objects.filter(report=report).exists():
                    raise ValidationError("Une évaluation de sévérité et une décision de triage sont requises avant la transition.")
                transition_report(
                    report=report,
                    actor=request.user,
                    target_status=target_status,
                    reason=request.POST.get("reason", ""),
                )
                create_local_notification(
                    user=report.author,
                    event_type=LocalNotification.EventType.TRIAGE,
                    title="État de rapport mis à jour",
                    body="Le statut de votre rapport a été mis à jour par le triage. Consultez votre espace privé pour le suivi autorisé.",
                    safe_reference=f"report:{report.id}",
                    idempotency_key=f"report-transition:{report.id}:{target_status}",
                )
                messages.success(request, "Le statut du rapport a été mis à jour avec un motif horodaté.")
            elif action == "relation":
                _require_current_triage_assignee(request=request, report=report)
                relation_type = request.POST.get("relation_type", "")
                if relation_type not in dict(ReportRelation.RelationType.choices):
                    raise ValidationError("Le type de relation sélectionné est invalide.")
                related_report = get_object_or_404(Report, pk=request.POST.get("related_report_id", ""), program=report.program)
                relation = relate_reports(
                    report=report,
                    related_report=related_report,
                    actor=request.user,
                    relation_type=relation_type,
                    rationale=request.POST.get("rationale", ""),
                )
                messages.success(request, f"Relation de cause racine #{relation.id} enregistrée avec justification.")
            elif action == "mediation_decision":
                mediation = MediationCase.objects.filter(report=report).select_related("initial_decider", "requested_by").first()
                if mediation is None:
                    raise ValidationError("Aucune médiation ouverte n’est disponible pour ce rapport.")
                reviewer = get_object_or_404(
                    User,
                    pk=request.POST.get("independent_reviewer_id", ""),
                    platform_role=User.PlatformRole.TRIAGER,
                )
                decide_mediation(
                    case=mediation,
                    mediator=request.user,
                    independent_reviewer=reviewer,
                    decision=request.POST.get("mediation_decision", ""),
                )
                messages.success(request, "La médiation a été décidée avec un second regard indépendant.")
            elif action == "remediation_start":
                _require_current_triage_assignee(request=request, report=report)
                owner = get_object_or_404(User, pk=request.POST.get("remediation_owner_id", ""))
                if not OrganizationMembership.objects.filter(organization=report.organization, user=owner).exists():
                    raise ValidationError("Le propriétaire de remédiation doit être membre de l’organisation concernée.")
                due_at = parse_datetime(request.POST.get("target_due_at", ""))
                if due_at is None:
                    raise ValidationError("L’échéance de remédiation est invalide.")
                if timezone.is_naive(due_at):
                    due_at = timezone.make_aware(due_at, timezone.get_current_timezone())
                start_remediation(
                    report=report,
                    actor=request.user,
                    owner=owner,
                    target_due_at=due_at,
                    plan=request.POST.get("remediation_plan", ""),
                )
                messages.success(request, "Le plan de remédiation est créé et attribué à son propriétaire organisationnel.")
            elif action == "remediation_validate":
                _require_current_triage_assignee(request=request, report=report)
                remediation = get_object_or_404(RemediationTracking, report=report)
                outcome = request.POST.get("validation_outcome", "")
                if outcome not in dict(FixValidation.Outcome.choices):
                    raise ValidationError("Le résultat de validation sélectionné est invalide.")
                validate_fix(
                    remediation=remediation,
                    validator=request.user,
                    outcome=outcome,
                    notes=request.POST.get("validation_notes", ""),
                )
                messages.success(request, "La validation indépendante de correction est enregistrée.")
            elif action == "reward_entitlement":
                _require_current_triage_assignee(request=request, report=report)
                entitlement = create_reward_entitlement(
                    report=report,
                    proposer=request.user,
                    amount_xof=int(request.POST.get("amount_xof", "0")),
                    rationale=request.POST.get("rationale", ""),
                )
                create_local_notification(
                    user=entitlement.beneficiary,
                    event_type=LocalNotification.EventType.REWARD,
                    title="Droit à récompense créé",
                    body="Un droit à récompense est en attente de contrôles finance indépendants. Aucun paiement n’est initié dans cet environnement.",
                    safe_reference=f"reward:{entitlement.id}",
                    idempotency_key=f"reward-entitlement:{entitlement.id}",
                )
                messages.success(request, f"Le droit à récompense #{entitlement.id} est transmis à la finance pour contrôle indépendant.")
            else:
                raise ValidationError("Action de triage inconnue.")
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
        return redirect("experience-triage-report-detail", report_id=report.id)

    assignment = _triage_assignment_for(report=report)
    latest_assessment = report.severity_assessments.order_by("-version", "-id").first()
    decision = TriageDecision.objects.filter(report=report).select_related("decided_by").first()
    mediation = MediationCase.objects.filter(report=report).select_related("requested_by", "initial_decider", "mediator", "independent_reviewer").first()
    remediation = RemediationTracking.objects.filter(report=report).select_related("owner").prefetch_related("validations__validator").first()
    excluded_mediation_ids = {request.user.id, report.author_id}
    if mediation:
        excluded_mediation_ids.add(mediation.initial_decider_id)
    mediation_reviewers = User.objects.filter(platform_role=User.PlatformRole.TRIAGER).exclude(pk__in=excluded_mediation_ids).order_by("email")
    remediation_owners = (
        OrganizationMembership.objects.filter(organization=report.organization)
        .select_related("user")
        .exclude(user__organization_conflicts__organization=report.organization, user__organization_conflicts__active=True)
        .order_by("user__email")
    )
    reward_entitlement = RewardEntitlement.objects.filter(report=report).select_related("beneficiary").first()
    outgoing_relations = report.outgoing_relations.select_related("related_report", "created_by").order_by("-created_at", "-id")
    incoming_relations = report.incoming_relations.select_related("report", "created_by").order_by("-created_at", "-id")
    relation_candidates = Report.objects.filter(program=report.program).exclude(pk=report.id).order_by("-created_at", "-id")
    return render(
        request,
        "experience/triage_report_detail.html",
        {
            "report": report,
            "assignment": assignment,
            "latest_assessment": latest_assessment,
            "decision": decision,
            "mediation": mediation,
            "can_decide_mediation": bool(mediation and mediation.status != MediationCase.Status.DECIDED and mediation.initial_decider_id != request.user.id),
            "mediation_reviewers": mediation_reviewers,
            "remediation": remediation,
            "remediation_owners": remediation_owners,
            "remediation_outcomes": FixValidation.Outcome.choices,
            "triage_events": report.triage_events.all(),
            "reward_entitlement": reward_entitlement,
            "outgoing_relations": outgoing_relations,
            "incoming_relations": incoming_relations,
            "relation_candidates": relation_candidates,
            "relation_types": ReportRelation.RelationType.choices,
            "is_assignee": bool(assignment and assignment.assigned_to_id == request.user.id),
            "can_claim": bool(
                report.status in {Report.Status.SUBMITTED, Report.Status.IN_TRIAGE, Report.Status.INFORMATION_REQUIRED}
                and (assignment is None or assignment.assigned_to_id == request.user.id)
            ),
            "queues": TriageAssignment.Queue.choices,
            "severities": SeverityAssessment.TechnicalSeverity.choices,
            "priorities": TriageDecision.BusinessPriority.choices,
            "eligibilities": TriageDecision.RewardEligibility.choices,
            "decision_reason_codes": TriageDecision.ReasonCode.choices,
            "transition_targets": [
                (Report.Status.INFORMATION_REQUIRED, "Information requise"),
                (Report.Status.VALID, "Valider le rapport"),
                (Report.Status.OUT_OF_SCOPE, "Classer hors périmètre"),
                (Report.Status.NON_REPRODUCIBLE, "Classer non reproductible"),
            ],
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def finance_console_view(request):
    if not has_platform_permission(user=request.user, permission="reward.approve"):
        raise PermissionDenied("Console finance refusée.")
    if request.method == "POST":
        action = request.POST.get("action", "")
        entitlement = get_object_or_404(RewardEntitlement, pk=request.POST.get("entitlement_id", "")) if action != "reconcile" else None
        try:
            if action == "approval":
                entitlement = approve_reward(
                    entitlement=entitlement,
                    approver=request.user,
                    approved=request.POST.get("approved") == "yes",
                    reason=request.POST.get("reason", ""),
                )
                create_local_notification(
                    user=entitlement.beneficiary,
                    event_type=LocalNotification.EventType.REWARD,
                    title="Décision finance enregistrée",
                    body="Une décision finance a été ajoutée à votre droit à récompense. Aucun fonds n’est transmis dans cet environnement.",
                    safe_reference=f"reward:{entitlement.id}",
                    idempotency_key=f"reward-approval:{entitlement.id}:{request.user.id}",
                )
                messages.success(request, "La décision finance est enregistrée dans le journal de récompense local.")
            elif action == "beneficiary_verify":
                profile = get_object_or_404(BeneficiaryProfile, pk=request.POST.get("beneficiary_profile_id", ""), user=entitlement.beneficiary)
                verify_beneficiary(profile=profile, reviewer=request.user)
                create_local_notification(
                    user=profile.user,
                    event_type=LocalNotification.EventType.REWARD,
                    title="Profil de bénéficiaire vérifié",
                    body="Votre référence de bénéficiaire a été vérifiée par la finance. Aucun portefeuille ni paiement réel n’est connecté.",
                    safe_reference=f"beneficiary:{profile.id}",
                    idempotency_key=f"beneficiary-verified:{profile.id}",
                )
                messages.success(request, "Le profil de bénéficiaire est vérifié par un rôle finance indépendant.")
            elif action == "sandbox_order":
                order = create_payment_order(
                    entitlement=entitlement,
                    actor=request.user,
                    idempotency_key=f"ui-sandbox-order:{entitlement.id}",
                    provider=SandboxPaymentProvider(LOCAL_SANDBOX_PAYMENT_SECRET),
                )
                create_local_notification(
                    user=entitlement.beneficiary,
                    event_type=LocalNotification.EventType.REWARD,
                    title="Ordre de règlement préparé",
                    body="Un ordre de règlement a été enregistré pour contrôle. Aucun fournisseur externe ni transfert de fonds n’est impliqué.",
                    safe_reference=f"reward:{entitlement.id}",
                    idempotency_key=f"sandbox-order:{order.id}",
                )
                messages.success(request, f"L’ordre de règlement {order.provider_reference} est enregistré. Aucun fonds n’a été transmis.")
            elif action == "cancel":
                cancel_reward(entitlement=entitlement, actor=request.user, reason=request.POST.get("reason", ""))
                messages.success(request, "L’annulation compensatoire est inscrite dans le grand livre local. Aucun fonds n’a été transmis.")
            elif action == "reconcile":
                report = reconcile_sandbox_payments(actor=request.user)
                messages.success(request, f"Le rapprochement interne est enregistré ({report.exception_count} exception(s)).")
            else:
                raise ValidationError("Action finance inconnue.")
        except (PermissionDenied, ValidationError) as exc:
            messages.error(request, " ".join(exc.messages) if hasattr(exc, "messages") else str(exc))
        return redirect("experience-finance-console")
    context = finance_console(user=request.user)
    context.update(
        {
            "reconciliations": ReconciliationReport.objects.select_related("created_by").order_by("-created_at")[:10],
            "ledger_entries": LedgerEntry.objects.select_related("entitlement").order_by("-created_at")[:30],
        }
    )
    return render(request, "experience/finance_console.html", context)


@login_required
@require_http_methods(["GET", "POST"])
def administration_console_view(request):
    if not has_platform_permission(user=request.user, permission="platform.admin"):
        raise PermissionDenied("Console administrative refusée.")
    if request.method == "POST":
        action = request.POST.get("action", "organization_review")
        try:
            if action == "organization_review":
                organization = get_object_or_404(Organization, pk=request.POST.get("organization_id", ""))
                status = request.POST.get("verification_status", "")
                reviewer_reference = request.POST.get("reviewer_reference", "").strip()
                notes = request.POST.get("notes", "")
                if status not in dict(Organization.VerificationStatus.choices):
                    raise ValidationError("Le statut de vérification sélectionné est invalide.")
                if len(reviewer_reference) < 3:
                    raise ValidationError("Une référence de revue administrative est obligatoire.")
                set_verification_status(
                    organization=organization,
                    status=status,
                    reviewer_reference=reviewer_reference,
                    notes=notes,
                )
                record_organization_change(
                    organization=organization,
                    actor=request.user,
                    action="organization.verification_reviewed",
                    metadata={"status": status, "reviewer_reference": reviewer_reference},
                )
                messages.success(request, f"La vérification de « {organization.name} » est enregistrée.")
            elif action == "scope_review":
                scope = get_object_or_404(AssetScope, pk=request.POST.get("scope_id", ""))
                reviewed_scope = review_program_scope(
                    administrator=request.user,
                    scope=scope,
                    evidence_reference=request.POST.get("evidence_reference", ""),
                    reviewer_reference=request.POST.get("reviewer_reference", ""),
                )
                messages.success(request, f"Le scope « {reviewed_scope.asset} » est vérifié et journalisé.")
            elif action == "program_publish":
                program = get_object_or_404(Program, pk=request.POST.get("program_id", ""))
                published_program = publish_program_after_admin_review(
                    administrator=request.user,
                    program=program,
                    reviewer_reference=request.POST.get("reviewer_reference", ""),
                )
                messages.success(request, f"Le programme « {published_program.name} » est publié après revue administrative.")
            elif action == "readiness_check":
                check_code = request.POST.get("check_code", "")
                status = request.POST.get("status", "")
                reference = request.POST.get("reference", "").strip()
                if LOCAL_CHECKS.get(check_code) != "pass":
                    raise ValidationError("Seuls les contrôles locaux vérifiables peuvent être enregistrés dans cette console.")
                if status not in {ReadinessCheck.Status.PASS, ReadinessCheck.Status.BLOCKED}:
                    raise ValidationError("Le statut de contrôle local est invalide.")
                if len(reference) < 3:
                    raise ValidationError("Une référence interne de contrôle est obligatoire.")
                record_local_readiness_check(
                    actor=request.user,
                    check_code=check_code,
                    status=status,
                    evidence={"reference": reference, "recorded_via": "administration_console", "external_service_called": False},
                )
                messages.success(request, "Le contrôle local est enregistré de manière append-only ; aucun service externe n’a été appelé.")
            elif action == "resilience_simulation":
                dependency = request.POST.get("dependency", "")
                operation = request.POST.get("operation", "")
                observed_mode = request.POST.get("observed_mode", "")
                if dependency not in ResilienceExercise.Dependency.values:
                    raise ValidationError("La dépendance simulée est invalide.")
                exercise = simulate_dependency_degradation(
                    actor=request.user,
                    dependency=dependency,
                    operation=operation,
                    observed_mode=observed_mode or None,
                )
                outcome = "conforme" if exercise.passed else "à analyser"
                messages.success(request, f"La simulation locale de résilience est enregistrée : résultat {outcome}.")
            elif action == "go_no_go_local":
                assessment = create_go_no_go_assessment(
                    actor=request.user,
                    local_evidence={
                        "readiness_checks": ReadinessCheck.objects.count(),
                        "resilience_exercises": ResilienceExercise.objects.count(),
                        "created_via": "administration_console",
                    },
                    external_completed=False,
                )
                messages.success(request, f"La grille locale go/no-go est enregistrée : {assessment.status}. Les blocages externes restent visibles.")
            else:
                raise ValidationError("Action administrative inconnue.")
        except (PermissionDenied, ValidationError) as exc:
            messages.error(request, " ".join(exc.messages) if hasattr(exc, "messages") else str(exc))
        return redirect("experience-administration-console")
    return render(request, "experience/administration_console.html", administration_console(user=request.user))


@login_required
@require_http_methods(["GET", "POST"])
def readiness_console_view(request):
    if not (
        has_platform_permission(user=request.user, permission="platform.admin") or has_platform_permission(user=request.user, permission="security.review")
    ):
        raise PermissionDenied("Console de préparation refusée.")
    if request.method == "POST":
        action = request.POST.get("action", "")
        try:
            if action == "readiness_check":
                check_code = request.POST.get("check_code", "")
                status = request.POST.get("status", "")
                reference = request.POST.get("reference", "").strip()
                if LOCAL_CHECKS.get(check_code) != "pass":
                    raise ValidationError("Seuls les contrôles locaux vérifiables peuvent être enregistrés dans cette console.")
                if status not in {ReadinessCheck.Status.PASS, ReadinessCheck.Status.BLOCKED}:
                    raise ValidationError("Le statut de contrôle local est invalide.")
                if len(reference) < 3:
                    raise ValidationError("Une référence interne de contrôle est obligatoire.")
                record_local_readiness_check(
                    actor=request.user,
                    check_code=check_code,
                    status=status,
                    evidence={"reference": reference, "recorded_via": "readiness_console", "external_service_called": False},
                )
                messages.success(request, "Le contrôle local est append-only ; aucun service externe n’a été appelé.")
            elif action == "integrity_snapshot":
                snapshot = record_consolidated_integrity_snapshot(actor=request.user)
                messages.success(
                    request,
                    f"Instantané consolidé append-only enregistré : {snapshot.get_status_display()}. Aucun service externe n’a été appelé.",
                )
            elif action == "resilience_simulation":
                dependency = request.POST.get("dependency", "")
                operation = request.POST.get("operation", "")
                observed_mode = request.POST.get("observed_mode", "")
                if dependency not in ResilienceExercise.Dependency.values:
                    raise ValidationError("La dépendance simulée est invalide.")
                exercise = simulate_dependency_degradation(
                    actor=request.user,
                    dependency=dependency,
                    operation=operation,
                    observed_mode=observed_mode or None,
                )
                messages.success(request, f"Simulation locale enregistrée : {'conforme' if exercise.passed else 'à analyser'}.")
            elif action == "go_no_go_local":
                assessment = create_go_no_go_assessment(
                    actor=request.user,
                    local_evidence={
                        "readiness_checks": ReadinessCheck.objects.count(),
                        "resilience_exercises": ResilienceExercise.objects.count(),
                        "created_via": "readiness_console",
                    },
                    external_completed=False,
                )
                messages.success(request, f"Grille locale enregistrée : {assessment.status}. Les blocages externes restent ouverts.")
            else:
                raise ValidationError("Action de préparation inconnue.")
        except (PermissionDenied, ValidationError) as exc:
            messages.error(request, " ".join(exc.messages) if hasattr(exc, "messages") else str(exc))
        return redirect("experience-readiness-console")
    return render(request, "experience/readiness_console.html", readiness_console(user=request.user))


@login_required
@require_http_methods(["GET"])
def local_integrity_console_view(request):
    return render(request, "experience/local_integrity_console.html", local_integrity_console(user=request.user))


@login_required
@require_http_methods(["GET", "POST"])
def privilege_review_console_view(request):
    if not (
        has_platform_permission(user=request.user, permission="platform.admin") or has_platform_permission(user=request.user, permission="security.review")
    ):
        raise PermissionDenied("Console de revue des privilèges refusée.")
    if request.method == "POST":
        try:
            snapshot = record_privilege_review_snapshot(
                actor=request.user,
                review_reference=request.POST.get("review_reference", ""),
            )
            messages.success(request, f"Instantané local append-only enregistré : {snapshot.review_reference}.")
        except (PermissionDenied, ValidationError) as exc:
            messages.error(request, " ".join(exc.messages) if hasattr(exc, "messages") else str(exc))
        return redirect("experience-privilege-review-console")
    return render(request, "experience/privilege_review_console.html", privilege_review_console(user=request.user))


@login_required
@require_http_methods(["GET", "POST"])
def academy_view(request):
    if request.method == "POST":
        if request.user.platform_role != User.PlatformRole.RESEARCHER:
            raise PermissionDenied("L’acceptation des règles de recherche est réservée aux comptes chercheur.")
        if request.POST.get("ethics_confirmation") != "on":
            messages.error(request, "Confirmez votre acceptation des règles d’éthique avant de continuer.")
        else:
            accept_current_ethics(learner=request.user)
            messages.success(request, "Votre acceptation des règles d’éthique a été enregistrée.")
            return redirect("experience-academy")
    context = academy_and_challenges(user=request.user)
    context.update({"ethics_rules_version": CURRENT_ETHICS_RULES_VERSION, "ethics_rules_text": CURRENT_ETHICS_RULES_TEXT})
    return render(request, "experience/academy.html", context)
