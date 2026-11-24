"""Adaptateur sandboxé de laboratoire ; aucune requête réseau ou cible externe n’est autorisée ici."""

from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.utils import timezone


@dataclass(frozen=True)
class SandboxProvision:
    reference: str
    network_policy: dict[str, str]
    quota_minutes: int
    created_at: datetime


class SandboxLabProvider:
    """Fournisseur en mémoire destiné aux tests et au contrat de sécurité de l’Académie."""

    provider_name = "sandbox-memory-v1"
    isolation_policy = {
        "egress": "deny-all",
        "ingress": "learner-session-only",
        "dns": "disabled",
        "external_targets": "forbidden",
    }

    def __init__(self):
        self._resources: dict[str, dict] = {}

    def provision(self, *, laboratory_code: str, learner_reference: str, quota_minutes: int) -> SandboxProvision:
        if quota_minutes <= 0:
            raise ValidationError("Le quota du laboratoire doit être positif.")
        reference = f"sandbox-{uuid4().hex}"
        created_at = timezone.now()
        self._resources[reference] = {
            "laboratory_code": laboratory_code,
            "learner_reference": learner_reference,
            "quota_minutes": quota_minutes,
            "network_policy": self.isolation_policy.copy(),
            "created_at": created_at,
            "state": "active",
            "destroyed_at": None,
        }
        return SandboxProvision(reference=reference, network_policy=self.isolation_policy.copy(), quota_minutes=quota_minutes, created_at=created_at)

    def verify_isolation(self, *, reference: str) -> dict[str, str]:
        resource = self._resources.get(reference)
        if not resource or resource["state"] != "active" or resource["network_policy"] != self.isolation_policy:
            raise ValidationError("La preuve d’isolation de la ressource sandbox est invalide.")
        return resource["network_policy"].copy()

    def destroy(self, *, reference: str) -> dict:
        resource = self._resources.get(reference)
        if not resource or resource["state"] != "active":
            raise ValidationError("La ressource sandbox est absente ou déjà détruite.")
        resource["state"] = "destroyed"
        resource["destroyed_at"] = timezone.now()
        return {"provider": self.provider_name, "reference": reference, "state": "destroyed", "destroyed_at": resource["destroyed_at"].isoformat()}


default_sandbox_provider = SandboxLabProvider()
