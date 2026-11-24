from django.conf import settings
from django.db import models

from apps.security.models import SecuritySubject


class LearningPath(models.Model):
    code = models.SlugField(max_length=64, unique=True)
    title = models.CharField(max_length=180)
    description = models.TextField()
    published = models.BooleanField(default=False)


class LearningModule(models.Model):
    path = models.ForeignKey(LearningPath, on_delete=models.CASCADE, related_name="modules")
    title = models.CharField(max_length=180)
    position = models.PositiveIntegerField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["path", "position"], name="unique_path_module_position")]


class Lesson(models.Model):
    module = models.ForeignKey(LearningModule, on_delete=models.CASCADE, related_name="lessons")
    title = models.CharField(max_length=180)
    content_reference = models.CharField(max_length=255)
    position = models.PositiveIntegerField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["module", "position"], name="unique_module_lesson_position")]


class EthicsAcceptance(models.Model):
    learner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="academy_ethics_acceptances")
    rules_version = models.CharField(max_length=40)
    rules_hash = models.CharField(max_length=128)
    accepted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["learner", "rules_hash"], name="unique_learner_ethics_hash")]


class Laboratory(models.Model):
    code = models.SlugField(max_length=64, unique=True)
    title = models.CharField(max_length=180)
    fictional_scenario = models.TextField()
    is_isolated = models.BooleanField(default=True)
    contains_external_target = models.BooleanField(default=False)
    active = models.BooleanField(default=True)
    default_quota_minutes = models.PositiveIntegerField(default=60)


class LabInstance(models.Model):
    class Status(models.TextChoices):
        PROVISIONED = "provisioned", "Provisionnée"
        DESTROYED = "destroyed", "Détruite"
        EXPIRED = "expired", "Expirée"

    laboratory = models.ForeignKey(Laboratory, on_delete=models.PROTECT, related_name="instances")
    learner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="lab_instances")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PROVISIONED)
    network_isolated = models.BooleanField(default=True)
    quota_minutes = models.PositiveIntegerField()
    expires_at = models.DateTimeField()
    provider_reference = models.CharField(max_length=128, unique=True, null=True, blank=True)
    isolation_proof = models.JSONField(default=dict)
    provisioned_at = models.DateTimeField(auto_now_add=True)
    destroyed_at = models.DateTimeField(null=True, blank=True)
    destruction_reason = models.CharField(max_length=240, blank=True)
    destruction_proof = models.JSONField(default=dict)


class LearningProgress(models.Model):
    learner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="academy_progress")
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="learner_progress")
    completed_at = models.DateTimeField(null=True, blank=True)
    score = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["learner", "lesson"], name="unique_learner_lesson_progress")]


class ReportingExercise(models.Model):
    module = models.ForeignKey(LearningModule, on_delete=models.CASCADE, related_name="reporting_exercises")
    prompt = models.TextField()
    minimum_score = models.PositiveSmallIntegerField(default=60)


class ReportingExerciseSubmission(models.Model):
    exercise = models.ForeignKey(ReportingExercise, on_delete=models.CASCADE, related_name="submissions")
    learner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="academy_exercise_submissions")
    response = models.TextField()
    score = models.PositiveSmallIntegerField(null=True, blank=True)
    assessed_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)


class RemediationExercise(models.Model):
    module = models.ForeignKey(LearningModule, on_delete=models.CASCADE, related_name="remediation_exercises")
    prompt = models.TextField()
    expected_controls = models.JSONField(default=list)


class RemediationExerciseSubmission(models.Model):
    exercise = models.ForeignKey(RemediationExercise, on_delete=models.CASCADE, related_name="submissions")
    learner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="academy_remediation_submissions")
    response = models.TextField()
    score = models.PositiveSmallIntegerField(null=True, blank=True)
    assessed_at = models.DateTimeField(null=True, blank=True)


class AcademyBadge(models.Model):
    code = models.SlugField(max_length=64, unique=True)
    title = models.CharField(max_length=120)
    criteria = models.TextField()


class LearnerBadge(models.Model):
    class Status(models.TextChoices):
        PENDING_REVIEW = "pending_review", "En attente de revue"
        AWARDED = "awarded", "Attribué"
        REVOKED = "revoked", "Retiré"

    badge = models.ForeignKey(AcademyBadge, on_delete=models.PROTECT, related_name="awards")
    learner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="academy_badges")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING_REVIEW)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="reviewed_badges")
    review_reason = models.TextField(blank=True)
    awarded_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["badge", "learner"], name="unique_badge_per_learner")]


class LearnerConductIncident(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Ouvert"
        FROZEN = "frozen", "Gelé"
        APPEALED = "appealed", "En recours"
        CLOSED = "closed", "Clôturé"

    learner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="academy_conduct_incidents")
    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="reported_academy_incidents")
    security_subject = models.ForeignKey(SecuritySubject, on_delete=models.PROTECT, null=True, blank=True, related_name="academy_incidents")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)
    description = models.TextField()
    decision_reason = models.TextField(blank=True)
    appeal_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
