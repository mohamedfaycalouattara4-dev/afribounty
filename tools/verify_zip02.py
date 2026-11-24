#!/usr/bin/env python3
"""Contrôle statique local des artefacts du socle AfriBounty ZIP 02."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_FILES = (
    "README.md",
    "MANIFEST.md",
    "TEST_REPORT.md",
    "requirements.lock",
    "requirements-dev.lock",
    "pyproject.toml",
    "manage.py",
    "config/celery.py",
    "config/asgi.py",
    "config/settings/base.py",
    "config/settings/production.py",
    "apps/core/tasks.py",
    "apps/core/logging.py",
    "apps/core/middleware.py",
    "deployment/nginx/afribounty.conf",
    "docs/16_asgi_redis_celery.md",
    "docs/17_variables_environnement.md",
    "docs/20_revue_technique.md",
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
    workflow = root / ".github/workflows/quality.yml"
    if workflow.is_file():
        content = workflow.read_text(encoding="utf-8")
        for item in ("ruff check", "manage.py test", "pip-audit", "verify_zip02.py"):
            if item not in content:
                findings.append(f"Contrôle CI absent : {item}")
    return findings


def main() -> int:
    findings = validate()
    if findings:
        print("Contrôle ZIP 02 : échec")
        print("\n".join(f"- {item}" for item in findings))
        return 1
    print("Contrôle ZIP 02 : succès — artefacts présents et secrets courants absents.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
