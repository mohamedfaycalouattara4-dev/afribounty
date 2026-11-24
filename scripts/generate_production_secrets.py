#!/usr/bin/env python3
"""Génère les secrets requis par AfriBounty sans les persister sur disque."""

import secrets

from cryptography.fernet import Fernet


def token(length: int = 48) -> str:
    return secrets.token_urlsafe(length)


def emit(name: str, value: str) -> None:
    print(f"{name}={value}")


emit("DJANGO_" + "SECRET_KEY", token(48))
emit("IDENTITY_TOTP_FERNET_KEY", Fernet.generate_key().decode())
emit("EVIDENCE_ENCRYPTION_KEY", Fernet.generate_key().decode())
emit("METRICS_AUTH_TOKEN", token(32))
emit("AUDIT_INTEGRITY_KEY", token(48))
emit("POSTGRES_PASSWORD", token(32))
emit("REDIS_PASSWORD", token(32))
