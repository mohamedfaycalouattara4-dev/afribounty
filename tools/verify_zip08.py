#!/usr/bin/env python3
"""Vérification statique du ZIP cumulatif 1 à 90, sans dépendance externe."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_FILES = (
    "README.md",
    "MANIFEST.md",
    "TEST_REPORT.md",
    "requirements.lock",
    "apps/reports/models.py",
    "apps/reports/triage.py",
    "apps/reports/migrations/0002_mediationcase_remediationtracking_fixvalidation_and_more.py",
    "apps/reports/migrations/0003_triageexportevent.py",
    "apps/academy/models.py",
    "apps/academy/providers.py",
    "apps/academy/services.py",
    "apps/academy/migrations/0001_initial.py",
    "apps/academy/migrations/0002_labinstance_destruction_proof_and_more.py",
    "apps/reputation/models.py",
    "apps/reputation/services.py",
    "apps/reputation/migrations/0001_initial.py",
    "apps/rewards/models.py",
    "apps/rewards/sandbox.py",
    "apps/rewards/services.py",
    "apps/rewards/migrations/0001_initial.py",
    "apps/integrations/models.py",
    "apps/integrations/services.py",
    "apps/integrations/migrations/0001_initial.py",
    "apps/experience/services.py",
    "apps/experience/views.py",
    "apps/experience/static/experience/afribounty.css",
    "apps/experience/templates/experience/base.html",
    "apps/readiness/models.py",
    "apps/readiness/services.py",
    "apps/readiness/migrations/0001_initial.py",
    "apps/reports/migrations/0004_reportdraft.py",
    "apps/common/errors.py",
    "tests/test_triage_and_academy.py",
    "tests/test_reputation_rewards.py",
    "tests/test_integrations_experience.py",
    "tests/test_experience_http.py",
    "tests/test_readiness.py",
    "ZIP07_08_SPEC.md",
    "ZIP09_10_SPEC.md",
    "ZIP11_12_SPEC.md",
    "docs/121_130_experience.md",
    "ZIP13_14_SPEC.md",
    "docs/TEST_COVERAGE.md",
    "docs/ASVS_MATRIX.md",
    "docs/OWASP_API_TOP10_MATRIX.md",
    "docs/SBOM_AND_SCANS.md",
    "docs/RESILIENCE_RESTORE_RUNBOOK.md",
    "docs/EXTERNAL_AUDIT_AND_INCIDENT_TABLETOP.md",
    "docs/PILOT_LAUNCH_PACK.md",
    "docs/GO_NO_GO_TEMPLATE.md",
)
FORBIDDEN_NAMES = {".env", ".env.local", "id_rsa", "id_ed25519"}
FORBIDDEN_MARKERS = ("BEGIN" + " PRIVATE KEY", "AK" + "IA", "DJANGO_SECRET_KEY" + "=")
TEXT_SUFFIXES = {".py", ".md", ".toml", ".yml", ".yaml", ".txt", ".conf"}


def validate(root: Path = ROOT) -> list[str]:
    findings = [f"Fichier requis absent : {item}" for item in REQUIRED_FILES if not (root / item).is_file()]
    for path in root.rglob("*"):
        if not path.is_file() or ".git" in path.parts or "__pycache__" in path.parts:
            continue
        relative = path.relative_to(root)
        if path.name in FORBIDDEN_NAMES:
            findings.append(f"Fichier sensible interdit : {relative}")
        elif path.suffix in TEXT_SUFFIXES:
            content = path.read_text(encoding="utf-8")
            if any(marker in content for marker in FORBIDDEN_MARKERS):
                findings.append(f"Marqueur de secret interdit : {relative}")
    return findings


def main() -> int:
    findings = validate()
    if findings:
        print("Contrôle ZIP 08 : échec")
        print("\n".join(f"- {item}" for item in findings))
        return 1
    print("Contrôle ZIP 14 : succès — artefacts 1 à 150 présents et secrets courants absents.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
