from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class ReputationSeason(models.Model):
    code = models.SlugField(max_length=48, unique=True)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    active = models.BooleanField(default=False)

    def clean(self):
        if self.ends_at <= self.starts_at:
            raise ValidationError("La fin d’une saison doit être postérieure à son début.")


class ReputationEvent(models.Model):
    class EventType(models.TextChoices):
        REPORT_ACCEPTED = "report_accepted", "Rapport accepté"
        CHALLENGE_VALIDATED = "challenge_validated", "Challenge validé"
        SCORE_CORRECTION = "score_correction", "Correction de score"
        MANUAL_ADJUSTMENT = "manual_adjustment", "Ajustement manuel"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="reputation_events")
    season = models.ForeignKey(ReputationSeason, on_delete=models.PROTECT, related_name="events")
    event_type = models.CharField(max_length=24, choices=EventType.choices)
    points = models.IntegerField()
    source_reference = models.CharField(max_length=128)
    idempotency_key = models.CharField(max_length=128, unique=True)
    reason = models.CharField(max_length=500)
    compensates = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True, related_name="compensations")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def save(self, *args, **kwargs):
        if self.pk and ReputationEvent.objects.filter(pk=self.pk).exists():
            raise ValidationError("Un événement de réputation est append-only et ne peut pas être modifié.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Un événement de réputation ne peut pas être supprimé.")


class ReputationProfile(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reputation_profiles")
    season = models.ForeignKey(ReputationSeason, on_delete=models.CASCADE, related_name="profiles")
    points = models.IntegerField(default=0)
    rank = models.PositiveIntegerField(null=True, blank=True)
    recalculated_at = models.DateTimeField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "season"], name="unique_reputation_profile_season")]


class ResearcherPublicProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="public_researcher_profile")
    public_alias = models.CharField(max_length=80)
    opted_in = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)


class Challenge(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Brouillon"
        OPEN = "open", "Ouvert"
        CLOSED = "closed", "Fermé"

    code = models.SlugField(max_length=64, unique=True)
    title = models.CharField(max_length=180)
    fictional_scenario = models.TextField()
    rules_version = models.CharField(max_length=40)
    rules_hash = models.CharField(max_length=128)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    is_isolated = models.BooleanField(default=True)
    contains_external_target = models.BooleanField(default=False)

    def clean(self):
        if self.ends_at <= self.starts_at:
            raise ValidationError("La fin du challenge doit être postérieure à son début.")


class ChallengeEnrollment(models.Model):
    challenge = models.ForeignKey(Challenge, on_delete=models.CASCADE, related_name="enrollments")
    learner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="challenge_enrollments")
    rules_accepted_at = models.DateTimeField()
    eligibility_snapshot = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["challenge", "learner"], name="unique_challenge_enrollment")]


class ChallengeResult(models.Model):
    class ReviewStatus(models.TextChoices):
        PENDING = "pending", "En attente"
        APPROVED = "approved", "Approuvé"
        REJECTED = "rejected", "Rejeté"
        MANUAL_REVIEW = "manual_review", "Revue manuelle"

    enrollment = models.OneToOneField(ChallengeEnrollment, on_delete=models.CASCADE, related_name="result")
    submitted_score = models.PositiveIntegerField()
    submission_reference = models.CharField(max_length=128)
    anti_cheat_status = models.CharField(max_length=24, default="pending")
    review_status = models.CharField(max_length=24, choices=ReviewStatus.choices, default=ReviewStatus.PENDING)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="reviewed_challenge_results")
    review_reason = models.TextField(blank=True)
    reputation_event = models.OneToOneField(ReputationEvent, on_delete=models.PROTECT, null=True, blank=True, related_name="challenge_result")
    submitted_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)


class ScoreDispute(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Ouverte"
        RESOLVED = "resolved", "Résolue"
        REJECTED = "rejected", "Rejetée"

    result = models.ForeignKey(ChallengeResult, on_delete=models.PROTECT, related_name="disputes")
    requester = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="score_disputes")
    reason = models.TextField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)
    resolved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="resolved_score_disputes")
    resolution = models.TextField(blank=True)
    correction_event = models.OneToOneField(ReputationEvent, on_delete=models.PROTECT, null=True, blank=True, related_name="score_dispute_correction")
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)


class ReputationExportEvent(models.Model):
    season = models.ForeignKey(ReputationSeason, on_delete=models.PROTECT, related_name="exports")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="reputation_exports")
    aggregate = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
