"""Contrat de préparation des fournisseurs de preuve externes, sans activation implicite."""

from django.core.exceptions import ImproperlyConfigured

from apps.reports.models import EvidencePipelineState, ReportEvidence


EXTERNAL_EVIDENCE_CAPABILITIES = ("private_object_storage", "malware_scanning", "dlp_inspection")


def external_evidence_pipeline_readiness() -> dict:
    """Expose les capacités attendues, mais confirme qu’aucun fournisseur n’est connecté."""
    return {
        capability: {"enabled": False, "provider": "disabled", "activation_requires": "validation explicite, contrat et configuration vérifiée"}
        for capability in EXTERNAL_EVIDENCE_CAPABILITIES
    }


def require_external_evidence_activation(*, capability: str) -> None:
    if capability not in EXTERNAL_EVIDENCE_CAPABILITIES:
        raise ImproperlyConfigured("La capacité externe de preuve demandée est inconnue.")
    raise ImproperlyConfigured(
        "Aucun fournisseur externe de preuve n’est activé. Une validation explicite, un contrat et une configuration vérifiée sont requis."
    )


def register_local_evidence_acceptance(*, evidence: ReportEvidence) -> EvidencePipelineState:
    """Conserve l’état local après les contrôles de type, signature et secret déjà appliqués."""
    state, _ = EvidencePipelineState.objects.update_or_create(
        evidence=evidence,
        defaults={
            "state": EvidencePipelineState.State.LOCAL_ACCEPTED,
            "storage_provider": "disabled",
            "malware_scanner": "disabled",
            "dlp_provider": "disabled",
            "external_release_allowed": False,
        },
    )
    return state


def evidence_pipeline_contract_report() -> dict:
    """Contrôle les invariants locaux sans appeler ni configurer de fournisseur externe."""
    checked_count = 0
    invalid_state_count = 0
    invalid_provider_count = 0
    release_allowed_count = 0
    for pipeline_state in EvidencePipelineState.objects.only(
        "state", "storage_provider", "malware_scanner", "dlp_provider", "external_release_allowed"
    ).iterator():
        checked_count += 1
        if pipeline_state.state != EvidencePipelineState.State.LOCAL_ACCEPTED:
            invalid_state_count += 1
        if any(
            provider != "disabled"
            for provider in (
                pipeline_state.storage_provider,
                pipeline_state.malware_scanner,
                pipeline_state.dlp_provider,
            )
        ):
            invalid_provider_count += 1
        if pipeline_state.external_release_allowed:
            release_allowed_count += 1
    return {
        "checked_count": checked_count,
        "invalid_state_count": invalid_state_count,
        "invalid_provider_count": invalid_provider_count,
        "release_allowed_count": release_allowed_count,
        "valid": invalid_state_count == 0 and invalid_provider_count == 0 and release_allowed_count == 0,
    }
