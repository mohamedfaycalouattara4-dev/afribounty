from collections import defaultdict

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.identity.services import has_platform_permission
from apps.reputation.models import (
    Challenge,
    ChallengeEnrollment,
    ChallengeResult,
    ReputationEvent,
    ReputationExportEvent,
    ReputationProfile,
    ReputationSeason,
    ScoreDispute,
)


POINT_RULES = {
    ReputationEvent.EventType.REPORT_ACCEPTED: {"low": 10, "medium": 25, "high": 60, "critical": 120},
    ReputationEvent.EventType.CHALLENGE_VALIDATED: {"base": 5, "per_score": 1},
}


def points_for(*, event_type: str, context: dict) -> int:
    if event_type == ReputationEvent.EventType.REPORT_ACCEPTED:
        severity = context.get("severity")
        if severity not in POINT_RULES[event_type]:
            raise ValidationError("Une sévérité reconnue est obligatoire pour ce calcul de points.")
        return POINT_RULES[event_type][severity]
    if event_type == ReputationEvent.EventType.CHALLENGE_VALIDATED:
        score = context.get("score")
        if not isinstance(score, int) or score < 0 or score > 100:
            raise ValidationError("Le score de challenge doit être un entier entre 0 et 100.")
        rule = POINT_RULES[event_type]
        return rule["base"] + rule["per_score"] * score
    raise ValidationError("Cette catégorie d’événement ne dispose pas de règle de points automatique.")


def active_season(*, at=None) -> ReputationSeason:
    now = at or timezone.now()
    season = ReputationSeason.objects.filter(active=True, starts_at__lte=now, ends_at__gt=now).first()
    if not season:
        raise ValidationError("Aucune saison de réputation active ne couvre cet instant.")
    return season


@transaction.atomic
def append_reputation_event(
    *,
    user,
    season: ReputationSeason,
    event_type: str,
    points: int,
    source_reference: str,
    idempotency_key: str,
    reason: str,
    compensates=None,
):
    if not reason.strip() or not source_reference.strip() or not idempotency_key.strip():
        raise ValidationError("Un événement requiert une source, une clé d’idempotence et un motif.")
    event, _ = ReputationEvent.objects.get_or_create(
        idempotency_key=idempotency_key.strip(),
        defaults={
            "user": user,
            "season": season,
            "event_type": event_type,
            "points": points,
            "source_reference": source_reference.strip(),
            "reason": reason.strip(),
            "compensates": compensates,
        },
    )
    if event.user_id != user.id or event.season_id != season.id:
        raise ValidationError("La clé d’idempotence est déjà liée à un événement différent.")
    return event


@transaction.atomic
def rebuild_profiles(*, season: ReputationSeason) -> list[ReputationProfile]:
    totals = ReputationEvent.objects.filter(season=season).values("user_id").annotate(total=Sum("points")).order_by("-total", "user_id")
    profiles = []
    rank = 0
    previous_total = None
    for index, row in enumerate(totals, start=1):
        if row["total"] != previous_total:
            rank = index
            previous_total = row["total"]
        profile, _ = ReputationProfile.objects.update_or_create(
            season=season,
            user_id=row["user_id"],
            defaults={"points": row["total"], "rank": rank, "recalculated_at": timezone.now()},
        )
        profiles.append(profile)
    return profiles


@transaction.atomic
def enroll_challenge(*, challenge: Challenge, learner) -> ChallengeEnrollment:
    now = timezone.now()
    if challenge.status != Challenge.Status.OPEN or not (challenge.starts_at <= now < challenge.ends_at):
        raise PermissionDenied("Ce challenge n’est pas ouvert aux inscriptions.")
    if not challenge.is_isolated or challenge.contains_external_target:
        raise PermissionDenied("Un challenge doit être isolé et ne comporter aucune cible externe.")
    if not learner.email_verified:
        raise PermissionDenied("Une adresse e-mail vérifiée est obligatoire pour participer au challenge.")
    enrollment, _ = ChallengeEnrollment.objects.get_or_create(
        challenge=challenge,
        learner=learner,
        defaults={"rules_accepted_at": now, "eligibility_snapshot": {"email_verified": True, "isolated": True}},
    )
    return enrollment


@transaction.atomic
def create_isolated_challenge(*, administrator, code: str, title: str, scenario: str, rules_version: str, rules_hash: str, starts_at, ends_at) -> Challenge:
    if not has_platform_permission(user=administrator, permission="platform.admin"):
        raise PermissionDenied("Un rôle administrateur est requis pour créer un challenge.")
    if not code.strip() or not title.strip() or len(scenario.strip()) < 20 or not rules_version.strip() or not rules_hash.strip():
        raise ValidationError("Le code, le titre, le scénario isolé et les règles versionnées sont obligatoires.")
    if ends_at <= starts_at:
        raise ValidationError("La fin du challenge doit être postérieure au début.")
    return Challenge.objects.create(
        code=code.strip(),
        title=title.strip(),
        fictional_scenario=scenario.strip(),
        rules_version=rules_version.strip(),
        rules_hash=rules_hash.strip(),
        starts_at=starts_at,
        ends_at=ends_at,
        status=Challenge.Status.DRAFT,
        is_isolated=True,
        contains_external_target=False,
    )


@transaction.atomic
def set_isolated_challenge_status(*, administrator, challenge: Challenge, status: str) -> Challenge:
    if not has_platform_permission(user=administrator, permission="platform.admin"):
        raise PermissionDenied("Un rôle administrateur est requis pour gérer un challenge.")
    if status not in {Challenge.Status.OPEN, Challenge.Status.CLOSED}:
        raise ValidationError("Seuls l’ouverture et la fermeture contrôlées sont disponibles.")
    if not challenge.is_isolated or challenge.contains_external_target:
        raise ValidationError("Seuls les challenges isolés sans cible externe peuvent être gérés ici.")
    challenge.status = status
    challenge.save(update_fields=["status"])
    return challenge


@transaction.atomic
def submit_challenge_result(*, enrollment: ChallengeEnrollment, learner, score: int, reference: str) -> ChallengeResult:
    if enrollment.learner_id != learner.id:
        raise PermissionDenied("Seul le participant peut soumettre son résultat.")
    if enrollment.challenge.status != Challenge.Status.OPEN or not enrollment.challenge.is_isolated or enrollment.challenge.contains_external_target:
        raise PermissionDenied("Ce challenge isolé n’accepte plus de soumission.")
    if not 0 <= score <= 100 or not reference.strip():
        raise ValidationError("Un score entre 0 et 100 et une référence locale sont obligatoires.")
    result, created = ChallengeResult.objects.get_or_create(
        enrollment=enrollment, defaults={"submitted_score": score, "submission_reference": reference.strip(), "anti_cheat_status": "pending"}
    )
    if not created and result.submitted_score != score:
        raise ValidationError("Une soumission existe déjà pour cette participation.")
    return result


@transaction.atomic
def validate_challenge_result(*, result: ChallengeResult, reviewer, anti_cheat_cleared: bool, approved: bool, reason: str) -> ChallengeResult:
    if reviewer.id == result.enrollment.learner_id:
        raise PermissionDenied("Un participant ne peut pas valider son propre résultat.")
    if not has_platform_permission(user=reviewer, permission="report.triage") and not has_platform_permission(user=reviewer, permission="platform.admin"):
        raise PermissionDenied("Seul un rôle de revue autorisé peut valider un résultat.")
    if result.review_status != ChallengeResult.ReviewStatus.PENDING:
        raise ValidationError("Un résultat déjà traité ne peut pas être validé une seconde fois.")
    if not reason.strip():
        raise ValidationError("La validation manuelle exige un motif.")
    result.reviewed_by = reviewer
    result.review_reason = reason.strip()
    result.reviewed_at = timezone.now()
    if not anti_cheat_cleared:
        result.anti_cheat_status = "flagged"
        result.review_status = ChallengeResult.ReviewStatus.MANUAL_REVIEW
    elif not approved:
        result.anti_cheat_status = "cleared"
        result.review_status = ChallengeResult.ReviewStatus.REJECTED
    else:
        season = active_season()
        points = points_for(event_type=ReputationEvent.EventType.CHALLENGE_VALIDATED, context={"score": result.submitted_score})
        event = append_reputation_event(
            user=result.enrollment.learner,
            season=season,
            event_type=ReputationEvent.EventType.CHALLENGE_VALIDATED,
            points=points,
            source_reference=f"challenge-result:{result.id}",
            idempotency_key=f"challenge-result:{result.id}:approved",
            reason="Résultat de challenge validé après contrôle anti-triche.",
        )
        result.anti_cheat_status = "cleared"
        result.review_status = ChallengeResult.ReviewStatus.APPROVED
        result.reputation_event = event
    result.save(update_fields=["reviewed_by", "review_reason", "reviewed_at", "anti_cheat_status", "review_status", "reputation_event"])
    return result


@transaction.atomic
def open_score_dispute(*, result: ChallengeResult, requester, reason: str) -> ScoreDispute:
    if requester.id != result.enrollment.learner_id:
        raise PermissionDenied("Seul le participant concerné peut contester son score.")
    if result.review_status != ChallengeResult.ReviewStatus.APPROVED:
        raise ValidationError("Seul un résultat approuvé peut faire l’objet d’une contestation.")
    if not reason.strip():
        raise ValidationError("Une contestation exige un motif.")
    return ScoreDispute.objects.create(result=result, requester=requester, reason=reason.strip())


@transaction.atomic
def resolve_score_dispute(*, dispute: ScoreDispute, reviewer, corrected_score: int | None, reason: str) -> ScoreDispute:
    if reviewer.id == dispute.requester_id:
        raise PermissionDenied("Le participant ne peut pas trancher sa propre contestation.")
    if not has_platform_permission(user=reviewer, permission="report.triage"):
        raise PermissionDenied("Un rôle de revue est obligatoire pour trancher une contestation.")
    if dispute.status != ScoreDispute.Status.OPEN or not reason.strip():
        raise ValidationError("La contestation doit être ouverte et la décision motivée.")
    if corrected_score is None:
        dispute.status = ScoreDispute.Status.REJECTED
    else:
        if not 0 <= corrected_score <= 100:
            raise ValidationError("Le score corrigé doit être compris entre 0 et 100.")
        original_event = dispute.result.reputation_event
        if not original_event:
            raise ValidationError("Le résultat ne possède pas d’événement de réputation à compenser.")
        corrected_points = points_for(event_type=ReputationEvent.EventType.CHALLENGE_VALIDATED, context={"score": corrected_score})
        compensation = append_reputation_event(
            user=dispute.requester,
            season=original_event.season,
            event_type=ReputationEvent.EventType.SCORE_CORRECTION,
            points=corrected_points - original_event.points,
            source_reference=f"score-dispute:{dispute.id}",
            idempotency_key=f"score-dispute:{dispute.id}:correction",
            reason="Correction de score décidée après contestation.",
            compensates=original_event,
        )
        dispute.correction_event = compensation
        dispute.status = ScoreDispute.Status.RESOLVED
    dispute.resolved_by = reviewer
    dispute.resolution = reason.strip()
    dispute.resolved_at = timezone.now()
    dispute.save(update_fields=["status", "resolved_by", "resolution", "resolved_at", "correction_event"])
    return dispute


@transaction.atomic
def export_anonymized_progress(*, season: ReputationSeason, actor) -> dict:
    if not has_platform_permission(user=actor, permission="platform.admin"):
        raise PermissionDenied("Un rôle administrateur est requis pour cet export agrégé.")
    buckets: dict[str, int] = defaultdict(int)
    for profile in ReputationProfile.objects.filter(season=season):
        bucket = "0-24" if profile.points < 25 else "25-74" if profile.points < 75 else "75+"
        buckets[bucket] += 1
    payload = {"season": season.code, "participants": sum(buckets.values()), "score_buckets": dict(buckets)}
    ReputationExportEvent.objects.create(season=season, actor=actor, aggregate=payload)
    return payload
