#!/usr/bin/env python3
"""Vérification statique du ZIP 03 sans dépendance externe."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_FILES = (
    "README.md",
    "MANIFEST.md",
    "TEST_REPORT.md",
    "requirements.lock",
    "config/settings/base.py",
    "apps/security/models.py",
    "apps/security/audit.py",
    "apps/security/rate_limit.py",
    "apps/security/retention.py",
    "apps/security/notifications.py",
    "apps/security/migrations/0001_initial.py",
    "docs/21_30_securite_observabilite.md",
    "docs/29_runbook_incident_acces_urgence.md",
    "docs/30_revue_securite.md",
    ".github/workflows/quality.yml",
)
FORBIDDEN_NAMES = {".env", ".env.local", "id_rsa", "id_ed25519"}
FORBIDDEN_MARKERS = ("BEGIN" + " PRIVATE KEY", "AK" + "IA", "DJANGO_SECRET_KEY" + "=")
TEXT_SUFFIXES = {".py", ".md", ".toml", ".yml", ".yaml", ".txt", ".conf"}


def validate(root: Path = ROOT) -> list[str]:
    findings = [f"Fichier requis absent : {item}" for item in REQUIRED_FILES if not (root / item).is_file()]
    for path in root.rglob("*"):
        if not path.is_file() or ".git" in path.parts:
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
        print("Contrôle ZIP 03 : échec")
        print("\n".join(f"- {item}" for item in findings))
        return 1
    print("Contrôle ZIP 03 : succès — artefacts présents et secrets courants absents.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
