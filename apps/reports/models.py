import os
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from apps.organizations.models import Organization
from apps.programs.models import Program
from apps.reports.storage import private_evidence_storage


def report_evidence_upload_path(instance, filename: str) -> str:
    extension = os.path.splitext(filename)[1].lower()[:12]
    return f"report_evidence/{instance.report_id}/evidence-{uuid4().hex}{extension}"


class Report(models.Model):
    class Status(models.TextChoices):
        SUBMITTED = "submitted", "Soumis"
        IN_TRIAGE = "in_triage", "En triage"
        INFORMATION_REQUIRED = "information_required", "Information requise"
        VALID = "valid", "Validé"
        OUT_OF_SCOPE = "out_of_scope", "Hors périmètre"
        DUPLICATE = "duplicate", "Doublon"
        NON_REPRODUCIBLE = "non_reproducible", "Non reproductible"
        REMEDIATION = "remediation", "En remédiation"
        RESOLVED = "resolved", "Résolu"
        DISCLOSURE_REVIEW = "disclosure_review", "Divulgation en revue"

    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name="reports")
    program = models.ForeignKey(Program, on_delete=models.PROTECT, related_name="reports")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="submitted_reports")
    title = models.CharField(max_length=240)
    asset = models.CharField(max_length=255)
    impact = models.TextField(default="")
    reproduction = models.TextField(default="")
    proposed_severity = models.CharField(max_length=20, blank=True, default="")
    vulnerability_category = models.CharField(max_length=48, blank=True, default="")
    cwe_reference = models.CharField(max_length=24, blank=True, default="")
    affected_version = models.CharField(max_length=120, blank=True, default="")
    environment_details = models.TextField(default="")
    quality_score = models.PositiveSmallIntegerField(default=0)
    quality_flags = models.JSONField(default=list)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.SUBMITTED)
    policy_version = models.CharField(max_length=40)
    policy_hash = models.CharField(max_length=128)
    scope_snapshot = models.JSONField(default=dict)
    scope_hash = models.CharField(max_length=64, blank=True)
    idempotency_key = models.CharField(max_length=96)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["program", "author", "idempotency_key"], name="unique_report_submission_idempotency")]


class ReportEvent(models.Model):
    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name="events")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="report_events")
    from_status = models.CharField(max_length=32)
    to_status = models.CharField(max_length=32)
    reason = models.CharField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]


class ReportDraft(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name="report_drafts")
    program = models.ForeignKey(Program, on_delete=models.PROTECT, related_name="report_drafts")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="report_drafts")
    title = models.CharField(max_length=240, blank=True)
    asset = models.CharField(max_length=255, blank=True)
    impact = models.TextField(blank=True)
    reproduction = models.TextField(blank=True)
    proposed_severity = models.CharField(max_length=20, blank=True)
    vulnerability_category = models.CharField(max_length=48, blank=True, default="")
    cwe_reference = models.CharField(max_length=24, blank=True, default="")
    affected_version = models.CharField(max_length=120, blank=True, default="")
    environment_details = models.TextField(blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["program", "author"], name="unique_report_draft_per_program_author")]


class ReportConversation(models.Model):
    report = models.OneToOneField(Report, on_delete=models.PROTECT, related_name="conversation")
    created_at = models.DateTimeField(auto_now_add=True)


class ReportMessage(models.Model):
    conversation = models.ForeignKey(ReportConversation, on_delete=models.PROTECT, related_name="messages")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="report_messages")
    body = models.TextField()
    idempotency_key = models.CharField(max_length=96)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["conversation", "author", "idempotency_key"],
                name="unique_report_message_idempotency",
            )
        ]


class ReportEvidence(models.Model):
    class Category(models.TextChoices):
        REPRODUCTION = "reproduction", "Reproduction"
        IMPACT = "impact", "Impact"
        REMEDIATION = "remediation", "Remédiation"

    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name="evidence_items")
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="uploaded_report_evidence")
    category = models.CharField(max_length=24, choices=Category.choices, default=Category.REPRODUCTION)
    original_name = models.CharField(max_length=180)
    content_type = models.CharField(max_length=100)
    byte_size = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64)
    artifact = models.FileField(storage=private_evidence_storage, upload_to=report_evidence_upload_path)
    idempotency_key = models.CharField(max_length=96)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["report", "uploaded_by", "idempotency_key"],
                name="unique_report_evidence_idempotency",
            )
        ]


class EvidencePipelineState(models.Model):
    class State(models.TextChoices):
        LOCAL_ACCEPTED = "local_accepted", "Acceptée par les contrôles locaux"
        EXTERNAL_QUARANTINE_PENDING = "external_quarantine_pending", "Quarantaine externe en attente"
        EXTERNAL_RELEASED = "external_released", "Libérée après contrôles externes"
        REJECTED = "rejected", "Refusée"

    evidence = models.OneToOneField(ReportEvidence, on_delete=models.CASCADE, related_name="pipeline_state")
    state = models.CharField(max_length=40, choices=State.choices, default=State.LOCAL_ACCEPTED)
    storage_provider = models.CharField(max_length=32, default="disabled")
    malware_scanner = models.CharField(max_length=32, default="disabled")
    dlp_provider = models.CharField(max_length=32, default="disabled")
    external_release_allowed = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)


class TriageAssignment(models.Model):
    class Queue(models.TextChoices):
        PRE_TRIAGE = "pre_triage", "Pré-triage"
        TECHNICAL = "technical", "Triage technique"
        MEDIATION = "mediation", "Médiation"

    report = models.OneToOneField(Report, on_delete=models.CASCADE, related_name="triage_assignment")
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="triage_assignments")
    queue = models.CharField(max_length=24, choices=Queue.choices, default=Queue.PRE_TRIAGE)
    reason = models.CharField(max_length=500)
    assigned_at = models.DateTimeField(auto_now_add=True)


class SeverityAssessment(models.Model):
    class TechnicalSeverity(models.TextChoices):
        INFORMATIONAL = "informational", "Informationnelle"
        LOW = "low", "Faible"
        MEDIUM = "medium", "Moyenne"
        HIGH = "high", "Élevée"
        CRITICAL = "critical", "Critique"

    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name="severity_assessments")
    evaluator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="severity_assessments")
    technical_severity = models.CharField(max_length=20, choices=TechnicalSeverity.choices)
    scoring_vector = models.CharField(max_length=256, blank=True)
    justification = models.TextField()
    version = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["report", "version"], name="unique_report_severity_version")]
        ordering = ["report_id", "version"]


class TriageDecision(models.Model):
    class ReasonCode(models.TextChoices):
        PENDING = "pending", "À préciser"
        VALID_CONFIRMED = "valid_confirmed", "Vulnérabilité confirmée"
        DUPLICATE_ROOT_CAUSE = "duplicate_root_cause", "Doublon de cause racine"
        OUT_OF_SCOPE = "out_of_scope", "Hors périmètre"
        NON_REPRODUCIBLE = "non_reproducible", "Non reproductible"
        ACCEPTED_RISK = "accepted_risk", "Risque accepté"
        INFORMATIONAL = "informational", "Informationnel"

    class BusinessPriority(models.TextChoices):
        LOW = "low", "Faible"
        MEDIUM = "medium", "Moyenne"
        HIGH = "high", "Élevée"
        URGENT = "urgent", "Urgente"

    class RewardEligibility(models.TextChoices):
        UNDETERMINED = "undetermined", "À déterminer"
        ELIGIBLE = "eligible", "Éligible"
        INELIGIBLE = "ineligible", "Non éligible"

    report = models.OneToOneField(Report, on_delete=models.CASCADE, related_name="triage_decision")
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="triage_decisions")
    business_priority = models.CharField(max_length=16, choices=BusinessPriority.choices)
    reward_eligibility = models.CharField(max_length=20, choices=RewardEligibility.choices)
    reason_code = models.CharField(max_length=32, choices=ReasonCode.choices, default=ReasonCode.PENDING)
    justification = models.TextField()
    decided_at = models.DateTimeField(auto_now=True)


class ReportSlaState(models.Model):
    class CommitmentState(models.TextChoices):
        UPCOMING = "upcoming", "À venir"
        DUE = "due", "À traiter bientôt"
        OVERDUE = "overdue", "Dépassé"
        COMPLETED = "completed", "Respecté"

    report = models.OneToOneField(Report, on_delete=models.CASCADE, related_name="sla_state")
    acknowledgement_due_at = models.DateTimeField()
    acknowledgement_completed_at = models.DateTimeField(null=True, blank=True)
    acknowledgement_state = models.CharField(max_length=16, choices=CommitmentState.choices, default=CommitmentState.UPCOMING)
    triage_due_at = models.DateTimeField()
    triage_completed_at = models.DateTimeField(null=True, blank=True)
    triage_state = models.CharField(max_length=16, choices=CommitmentState.choices, default=CommitmentState.UPCOMING)
    resolution_due_at = models.DateTimeField()
    resolution_completed_at = models.DateTimeField(null=True, blank=True)
    resolution_state = models.CharField(max_length=16, choices=CommitmentState.choices, default=CommitmentState.UPCOMING)
    updated_at = models.DateTimeField(auto_now=True)


class ReportSlaEscalationEvent(models.Model):
    class Checkpoint(models.TextChoices):
        ACKNOWLEDGEMENT = "acknowledgement", "Accusé de réception"
        TRIAGE = "triage", "Décision de triage"
        RESOLUTION = "resolution", "Résolution"

    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name="sla_escalations")
    checkpoint = models.CharField(max_length=20, choices=Checkpoint.choices)
    due_at = models.DateTimeField()
    idempotency_key = models.CharField(max_length=128, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)


class ReportRelation(models.Model):
    class RelationType(models.TextChoices):
        DUPLICATE_OF = "duplicate_of", "Doublon de"
        ADDITIONAL_IMPACT = "additional_impact", "Impact additionnel"

    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name="outgoing_relations")
    related_report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name="incoming_relations")
    relation_type = models.CharField(max_length=24, choices=RelationType.choices)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_report_relations")
    rationale = models.CharField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["report", "related_report", "relation_type"], name="unique_report_relation"),
            models.CheckConstraint(condition=~models.Q(report=models.F("related_report")), name="report_relation_not_self"),
        ]

    def clean(self):
        if self.report_id and self.related_report_id and self.report_id == self.related_report_id:
            raise ValidationError("Un rapport ne peut pas être lié à lui-même.")
        if self.report_id and self.related_report_id and self.report.program_id != self.related_report.program_id:
            raise ValidationError("Les rapports liés doivent relever du même programme.")


class RemediationTracking(models.Model):
    class Status(models.TextChoices):
        PLANNED = "planned", "Planifiée"
        IN_PROGRESS = "in_progress", "En cours"
        READY_FOR_VALIDATION = "ready_for_validation", "Prête à valider"
        VERIFIED = "verified", "Vérifiée"
        REJECTED = "rejected", "Validation rejetée"

    report = models.OneToOneField(Report, on_delete=models.CASCADE, related_name="remediation")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="owned_remediations")
    target_due_at = models.DateTimeField()
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.PLANNED)
    plan = models.TextField()
    updated_at = models.DateTimeField(auto_now=True)


class FixValidation(models.Model):
    class Outcome(models.TextChoices):
        ACCEPTED = "accepted", "Acceptée"
        REJECTED = "rejected", "Rejetée"

    remediation = models.ForeignKey(RemediationTracking, on_delete=models.CASCADE, related_name="validations")
    validator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="fix_validations")
    outcome = models.CharField(max_length=16, choices=Outcome.choices)
    notes = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)


class MediationCase(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Ouverte"
        UNDER_REVIEW = "under_review", "En revue"
        DECIDED = "decided", "Décidée"

    report = models.OneToOneField(Report, on_delete=models.CASCADE, related_name="mediation")
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="requested_mediations")
    initial_decider = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="initial_mediation_decisions",
    )
    mediator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="mediated_cases")
    independent_reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="independent_mediation_reviews",
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    request_reason = models.TextField()
    decision = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)


class TriageDecisionEvent(models.Model):
    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name="triage_events")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="triage_events")
    action = models.CharField(max_length=64)
    detail = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]


class TriageExportEvent(models.Model):
    """Trace d’un export exclusivement agrégé, sans contenu ni preuve de rapport."""

    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name="triage_exports")
    program = models.ForeignKey(Program, on_delete=models.PROTECT, related_name="triage_exports")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="triage_exports")
    aggregate = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
