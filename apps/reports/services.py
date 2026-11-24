from dataclasses import dataclass

import hashlib
import json
import os
import re

from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db import IntegrityError, transaction

from apps.common.errors import DomainPermissionDenied, InvalidIdempotencyKey, InvalidTransition
from apps.organizations.models import Organization
from apps.organizations.services import record_organization_change, require_organization_permission
from apps.programs.models import AssetScope, Program
from apps.programs.access import require_research_scope
from apps.reports.models import Report, ReportConversation, ReportDraft, ReportEvidence, ReportEvent, ReportMessage
from apps.reports.evidence_pipeline import register_local_evidence_acceptance
from apps.reports.sla import ensure_report_sla_state

User = get_user_model()
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    Report.Status.SUBMITTED: {Report.Status.IN_TRIAGE},
    Report.Status.IN_TRIAGE: {
        Report.Status.INFORMATION_REQUIRED,
        Report.Status.VALID,
        Report.Status.OUT_OF_SCOPE,
        Report.Status.DUPLICATE,
        Report.Status.NON_REPRODUCIBLE,
    },
    Report.Status.INFORMATION_REQUIRED: {Report.Status.IN_TRIAGE},
    Report.Status.VALID: {Report.Status.REMEDIATION},
    Report.Status.REMEDIATION: {Report.Status.RESOLVED},
    Report.Status.RESOLVED: {Report.Status.DISCLOSURE_REVIEW},
    Report.Status.OUT_OF_SCOPE: set(),
    Report.Status.DUPLICATE: set(),
    Report.Status.NON_REPRODUCIBLE: set(),
    Report.Status.DISCLOSURE_REVIEW: set(),
}


@dataclass(frozen=True)
class SubmissionResult:
    report: Report
    was_created: bool


@dataclass(frozen=True)
class MessageSendResult:
    message: ReportMessage
    was_created: bool


@dataclass(frozen=True)
class EvidenceCreateResult:
    evidence: ReportEvidence
    was_created: bool


ALLOWED_EVIDENCE_CONTENT_TYPES = {
    "application/json",
    "application/pdf",
    "image/jpeg",
    "image/png",
    "text/plain",
}
MAX_EVIDENCE_BYTES = 5 * 1024 * 1024
ALLOWED_EVIDENCE_EXTENSIONS = {
    "application/json": {".json"},
    "application/pdf": {".pdf"},
    "image/jpeg": {".jpg", ".jpeg"},
    "image/png": {".png"},
    "text/plain": {".log", ".txt"},
}
EICAR_MARKER = b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE"
SENSITIVE_TEXT_PATTERNS = (
    re.compile(r"(?i)\b(?:password|passwd|pwd)\s*[:=]\s*\S+"),
    re.compile(r"(?i)\b(?:authorization|x-api-key|api[_-]?key|secret|token)\s*[:=]\s*(?:bearer\s+)?[A-Za-z0-9_./+=-]{12,}"),
    re.compile(r"\b" + "AK" + "IA" + r"[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\bsk_(?:live|test)_[A-Za-z0-9]{16,}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)
REPORT_VULNERABILITY_CATEGORIES = {
    "access_control",
    "authentication",
    "business_logic",
    "configuration",
    "data_exposure",
    "injection",
    "other",
}


def _reject_secret_material(*values: str) -> None:
    content = "\n".join(value for value in values if value)
    if any(pattern.search(content) for pattern in SENSITIVE_TEXT_PATTERNS):
        raise ValidationError("Le rapport semble contenir un secret ou identifiant actif. Masquez-le avant de poursuivre.")


def _normalize_report_quality(
    *,
    vulnerability_category: str = "",
    cwe_reference: str = "",
    affected_version: str = "",
    environment_details: str = "",
) -> tuple[dict, int, list[str]]:
    category = vulnerability_category.strip().lower()
    cwe = cwe_reference.strip().upper()
    version = affected_version.strip()
    environment = environment_details.strip()
    if category and category not in REPORT_VULNERABILITY_CATEGORIES:
        raise ValidationError("La catégorie de vulnérabilité est invalide.")
    if cwe and not re.fullmatch(r"CWE-[1-9][0-9]{0,4}", cwe):
        raise ValidationError("La référence CWE doit respecter le format CWE-123.")
    if len(version) > 120:
        raise ValidationError("La version affectée ne peut pas dépasser 120 caractères.")
    if len(environment) > 2000:
        raise ValidationError("La description d’environnement ne peut pas dépasser 2 000 caractères.")
    _reject_secret_material(version, environment)
    flags = []
    if not category:
        flags.append("vulnerability_category_missing")
    if not cwe:
        flags.append("cwe_reference_missing")
    if not version:
        flags.append("affected_version_missing")
    if not environment:
        flags.append("environment_details_missing")
    score = 60 + (10 * (4 - len(flags)))
    return (
        {
            "vulnerability_category": category,
            "cwe_reference": cwe,
            "affected_version": version,
            "environment_details": environment,
        },
        score,
        flags,
    )


def _validate_evidence_payload(*, uploaded_file, content_type: str) -> str:
    original_name = os.path.basename((uploaded_file.name or "preuve").replace("\\", "/"))
    extension = os.path.splitext(original_name)[1].lower()
    if extension not in ALLOWED_EVIDENCE_EXTENSIONS[content_type]:
        raise ValidationError("L’extension du fichier ne correspond pas au type de preuve autorisé.")
    payload = uploaded_file.read()
    uploaded_file.seek(0)
    if EICAR_MARKER in payload:
        raise ValidationError("La preuve contient une signature de test antivirus et reste refusée.")
    if content_type == "application/pdf" and not payload.startswith(b"%PDF-"):
        raise ValidationError("La signature binaire ne correspond pas à un PDF valide.")
    if content_type == "image/png" and not payload.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValidationError("La signature binaire ne correspond pas à une image PNG valide.")
    if content_type == "image/jpeg" and not payload.startswith(b"\xff\xd8\xff"):
        raise ValidationError("La signature binaire ne correspond pas à une image JPEG valide.")
    if content_type == "application/json":
        try:
            text_sample = payload.decode("utf-8")
            json.loads(text_sample)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValidationError("La preuve JSON doit être un document UTF-8 valide.") from exc
        _reject_secret_material(text_sample)
    if content_type == "text/plain":
        try:
            text_sample = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValidationError("La preuve texte doit être encodée en UTF-8.") from exc
        _reject_secret_material(text_sample)
    return original_name[:180]


def _assert_program_belongs_to_organization(*, organization: Organization, program: Program) -> None:
    if program.organization_id != organization.id:
        raise DomainPermissionDenied("Le programme ne relève pas de l’organisation active.")


def _canonical_scope_snapshot(*, program: Program, scope: AssetScope) -> dict:
    """Conserve le contexte autorisé à la date de soumission, sans preuve de propriété sensible."""
    return {
        "asset": scope.asset,
        "asset_type": scope.asset_type,
        "ownership_verified": bool(scope.ownership_proof.approved_at),
        "ownership_verified_at": scope.ownership_proof.approved_at.isoformat(),
        "policy_hash": program.policy_hash,
        "policy_version": program.policy_version,
        "program_id": program.id,
        "safe_harbor_version": program.safe_harbor_version,
        "scope_id": scope.id,
    }


def scope_snapshot_hash(snapshot: dict) -> str:
    canonical = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def verify_report_scope_integrity(*, report: Report) -> bool:
    return bool(report.scope_snapshot and report.scope_hash) and scope_snapshot_hash(report.scope_snapshot) == report.scope_hash


def report_scope_integrity_report() -> dict:
    """Contrôle local sans contenu de rapport : seules les empreintes d’instantanés de scope sont comparées."""
    checked_count = 0
    missing_snapshot_count = 0
    mismatched_snapshot_count = 0
    for report in Report.objects.only("id", "scope_snapshot", "scope_hash").iterator():
        checked_count += 1
        if not report.scope_snapshot or not report.scope_hash:
            missing_snapshot_count += 1
        elif not verify_report_scope_integrity(report=report):
            mismatched_snapshot_count += 1
    return {
        "checked_count": checked_count,
        "missing_snapshot_count": missing_snapshot_count,
        "mismatched_snapshot_count": mismatched_snapshot_count,
        "valid": missing_snapshot_count == 0 and mismatched_snapshot_count == 0,
    }


def submit_report(
    *,
    organization: Organization,
    program: Program,
    author: User,
    title: str,
    asset: str,
    impact: str,
    reproduction: str,
    proposed_severity: str = "",
    vulnerability_category: str = "",
    cwe_reference: str = "",
    affected_version: str = "",
    environment_details: str = "",
    idempotency_key: str,
) -> SubmissionResult:
    key = idempotency_key.strip()
    if len(key) < 16:
        raise InvalidIdempotencyKey("La clé d’idempotence doit contenir au moins 16 caractères.")
    if not all([title.strip(), asset.strip(), impact.strip(), reproduction.strip()]):
        raise ValidationError("Le titre, l’actif, l’impact et les étapes de reproduction sont obligatoires.")
    _reject_secret_material(title, asset, impact, reproduction)
    quality, quality_score, quality_flags = _normalize_report_quality(
        vulnerability_category=vulnerability_category,
        cwe_reference=cwe_reference,
        affected_version=affected_version,
        environment_details=environment_details,
    )
    _assert_program_belongs_to_organization(organization=organization, program=program)
    scope = require_research_scope(user=author, program=program, asset=asset)
    snapshot = _canonical_scope_snapshot(program=program, scope=scope)
    snapshot_hash = scope_snapshot_hash(snapshot)
    existing = Report.objects.filter(program=program, author=author, idempotency_key=key).first()
    if existing:
        return SubmissionResult(report=existing, was_created=False)
    try:
        with transaction.atomic():
            report = Report.objects.create(
                organization=organization,
                program=program,
                author=author,
                title=title.strip(),
                asset=asset.strip(),
                impact=impact.strip(),
                reproduction=reproduction.strip(),
                proposed_severity=proposed_severity.strip(),
                quality_score=quality_score,
                quality_flags=quality_flags,
                policy_version=program.policy_version,
                policy_hash=program.policy_hash,
                scope_snapshot=snapshot,
                scope_hash=snapshot_hash,
                idempotency_key=key,
                **quality,
            )
            ReportEvent.objects.create(
                report=report, actor=author, from_status="", to_status=Report.Status.SUBMITTED, reason="Soumission initiale idempotente."
            )
            ensure_report_sla_state(report=report)
            return SubmissionResult(report=report, was_created=True)
    except IntegrityError:
        return SubmissionResult(report=Report.objects.get(program=program, author=author, idempotency_key=key), was_created=False)


@transaction.atomic
def save_report_draft(
    *,
    organization: Organization,
    program: Program,
    author: User,
    title: str = "",
    asset: str = "",
    impact: str = "",
    reproduction: str = "",
    proposed_severity: str = "",
    vulnerability_category: str = "",
    cwe_reference: str = "",
    affected_version: str = "",
    environment_details: str = "",
) -> ReportDraft:
    _assert_program_belongs_to_organization(organization=organization, program=program)
    _reject_secret_material(title, asset, impact, reproduction)
    quality, _, _ = _normalize_report_quality(
        vulnerability_category=vulnerability_category,
        cwe_reference=cwe_reference,
        affected_version=affected_version,
        environment_details=environment_details,
    )
    draft, _ = ReportDraft.objects.update_or_create(
        organization=organization,
        program=program,
        author=author,
        defaults={
            "title": title.strip(),
            "asset": asset.strip(),
            "impact": impact.strip(),
            "reproduction": reproduction.strip(),
            "proposed_severity": proposed_severity.strip(),
            **quality,
        },
    )
    return draft


def require_report_conversation_participant(*, report: Report, actor: User) -> str:
    if report.author_id == actor.id:
        return "researcher"
    require_organization_permission(user=actor, organization=report.organization, permission="report.message")
    return "organization"


def get_report_conversation(*, report: Report, actor: User) -> ReportConversation | None:
    require_report_conversation_participant(report=report, actor=actor)
    return ReportConversation.objects.filter(report=report).prefetch_related("messages__author").first()


def list_report_evidence(*, report: Report, actor: User):
    require_report_conversation_participant(report=report, actor=actor)
    return ReportEvidence.objects.filter(report=report).select_related("uploaded_by")


def evidence_integrity_report() -> dict:
    """Vérifie localement les octets déchiffrés de preuves privées sans rendre leur contenu accessible."""
    checked_count = 0
    missing_artifact_count = 0
    unreadable_artifact_count = 0
    mismatched_artifact_count = 0
    for evidence in ReportEvidence.objects.only("id", "artifact", "byte_size", "sha256").iterator():
        checked_count += 1
        if not evidence.artifact.name:
            missing_artifact_count += 1
            continue
        digest = hashlib.sha256()
        byte_count = 0
        try:
            evidence.artifact.open("rb")
            for chunk in evidence.artifact.chunks():
                digest.update(chunk)
                byte_count += len(chunk)
        except (FileNotFoundError, ImproperlyConfigured, OSError):
            unreadable_artifact_count += 1
            continue
        finally:
            evidence.artifact.close()
        if digest.hexdigest() != evidence.sha256 or byte_count != evidence.byte_size:
            mismatched_artifact_count += 1
    return {
        "checked_count": checked_count,
        "missing_artifact_count": missing_artifact_count,
        "unreadable_artifact_count": unreadable_artifact_count,
        "mismatched_artifact_count": mismatched_artifact_count,
        "valid": missing_artifact_count == 0 and unreadable_artifact_count == 0 and mismatched_artifact_count == 0,
    }


def add_report_evidence(*, report: Report, actor: User, uploaded_file, category: str, idempotency_key: str) -> EvidenceCreateResult:
    require_report_conversation_participant(report=report, actor=actor)
    key = idempotency_key.strip()
    if len(key) < 16:
        raise InvalidIdempotencyKey("La clé d’idempotence de la preuve doit contenir au moins 16 caractères.")
    if uploaded_file is None:
        raise ValidationError("Sélectionnez un fichier de preuve.")
    if category not in ReportEvidence.Category.values:
        raise ValidationError("La catégorie de preuve est invalide.")
    content_type = (getattr(uploaded_file, "content_type", "") or "").lower()
    if content_type not in ALLOWED_EVIDENCE_CONTENT_TYPES:
        raise ValidationError("Seuls PDF, PNG, JPEG, texte brut et JSON sont admis dans cette démonstration.")
    if uploaded_file.size <= 0 or uploaded_file.size > MAX_EVIDENCE_BYTES:
        raise ValidationError("La preuve doit peser entre 1 octet et 5 Mo.")
    original_name = _validate_evidence_payload(uploaded_file=uploaded_file, content_type=content_type)
    existing = ReportEvidence.objects.filter(report=report, uploaded_by=actor, idempotency_key=key).first()
    if existing:
        return EvidenceCreateResult(evidence=existing, was_created=False)
    digest = hashlib.sha256()
    for chunk in uploaded_file.chunks():
        digest.update(chunk)
    uploaded_file.seek(0)
    try:
        with transaction.atomic():
            evidence = ReportEvidence(
                report=report,
                uploaded_by=actor,
                category=category,
                original_name=original_name,
                content_type=content_type,
                byte_size=uploaded_file.size,
                sha256=digest.hexdigest(),
                idempotency_key=key,
            )
            evidence.artifact.save("evidence", uploaded_file, save=False)
            evidence.save()
            register_local_evidence_acceptance(evidence=evidence)
    except IntegrityError:
        return EvidenceCreateResult(
            evidence=ReportEvidence.objects.get(report=report, uploaded_by=actor, idempotency_key=key),
            was_created=False,
        )
    if report.author_id != actor.id:
        record_organization_change(
            organization=report.organization,
            actor=actor,
            action="report.evidence_added",
            metadata={"report_id": report.id, "evidence_id": evidence.id, "category": evidence.category},
        )
    return EvidenceCreateResult(evidence=evidence, was_created=True)


def send_report_message(*, report: Report, actor: User, body: str, idempotency_key: str) -> MessageSendResult:
    participant_type = require_report_conversation_participant(report=report, actor=actor)
    normalized_body = body.strip()
    normalized_key = idempotency_key.strip()
    if not normalized_body:
        raise ValidationError("Le message ne peut pas être vide.")
    if len(normalized_body) > 4000:
        raise ValidationError("Le message ne peut pas dépasser 4 000 caractères.")
    if len(normalized_key) < 16:
        raise InvalidIdempotencyKey("La clé d’idempotence du message doit contenir au moins 16 caractères.")
    try:
        with transaction.atomic():
            conversation, _ = ReportConversation.objects.get_or_create(report=report)
            existing = ReportMessage.objects.filter(
                conversation=conversation,
                author=actor,
                idempotency_key=normalized_key,
            ).first()
            if existing:
                return MessageSendResult(message=existing, was_created=False)
            message = ReportMessage.objects.create(
                conversation=conversation,
                author=actor,
                body=normalized_body,
                idempotency_key=normalized_key,
            )
    except IntegrityError:
        conversation = ReportConversation.objects.get(report=report)
        return MessageSendResult(
            message=ReportMessage.objects.get(conversation=conversation, author=actor, idempotency_key=normalized_key),
            was_created=False,
        )
    if participant_type == "organization":
        record_organization_change(
            organization=report.organization,
            actor=actor,
            action="conversation.message_sent",
            metadata={"report_id": report.id, "message_id": message.id},
        )
    return MessageSendResult(message=message, was_created=True)


def transition_report(*, report: Report, actor: User, target_status: str, reason: str) -> Report:
    if target_status not in ALLOWED_TRANSITIONS.get(report.status, set()):
        raise InvalidTransition(f"Transition interdite : {report.status} -> {target_status}.")
    if not reason.strip():
        raise InvalidTransition("Toute transition exige un motif explicite.")
    previous_status = report.status
    with transaction.atomic():
        report.status = target_status
        report.save(update_fields=["status", "updated_at"])
        ReportEvent.objects.create(report=report, actor=actor, from_status=previous_status, to_status=target_status, reason=reason.strip())
        ensure_report_sla_state(report=report)
    return report
