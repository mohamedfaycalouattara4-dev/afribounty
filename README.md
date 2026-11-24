# AfriBounty

AfriBounty est un socle Django de divulgation responsable et de gestion de rapports de sécurité. Il couvre les programmes, les rapports privés, le triage, la médiation, l’Académie, la réputation et les récompenses sandboxées.

Le projet adopte une approche **fail-closed** : aucune intégration externe sensible n’est activée par défaut, aucun paiement réel n’est effectué et aucune preuve privée n’est exposée par URL publique.

## Stack

- Python 3.12+, Django 5.2 et Django REST Framework.
- PostgreSQL, Redis, Celery, Uvicorn et Gunicorn.
- Authentification locale avec Argon2id, TOTP et WebAuthn/FIDO2.
- Docker et Docker Compose pour la préproduction.
- Ruff, pip-audit, compilation Python et GitHub Actions.

## Fonctionnalités techniques

- Autorisations multi-tenant et contrôles anti-IDOR.
- Rapports privés avec scope figé, validation de fichiers, empreintes et pipeline d’intégrité.
- Audit append-only avec vérification cryptographique.
- Rate limiting et contrôles de sécurité HTTP en mode production.
- Métriques agrégées et endpoints live/readiness protégés.
- Ledger sandboxé, idempotence, anti-rejeu et séparation des rôles.
- Image Docker non-root avec filesystem applicatif en lecture seule.
- Réseau backend interne, capabilities supprimées et `no-new-privileges`.
- Migrations séparées, worker Celery et readiness PostgreSQL/Redis.

## Architecture

```text
Client web
   │
   ▼
Gunicorn/Django ── Redis ── Celery worker
   │
   ▼
PostgreSQL + stockage privé prévu pour la préproduction
```

## Validation

La validation enregistrée dans le projet indique :

- migrations cohérentes ;
- suite Django verte ;
- Ruff et formatage validés ;
- compilation Python réussie ;
- audit des dépendances sans vulnérabilité connue au moment du contrôle ;
- vérification des artefacts de livraison réussie ;
- contrôle du profil de production réussi.

Les tests et contrôles se lancent avec :

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.lock -r requirements-dev.lock
export DJANGO_SETTINGS_MODULE=config.settings.test
python manage.py makemigrations --check --dry-run
python manage.py migrate --noinput
python manage.py test tests -v 2
ruff check .
ruff format --check .
pip-audit -r requirements.lock
```

## Préproduction Docker

```bash
cp .env.production.example .env.production
python scripts/generate_production_secrets.py
# Injecter les valeurs dans un coffre de secrets, sans les versionner.
docker compose --env-file .env.production -f deployment/docker-compose.production.yml build --pull
docker compose --env-file .env.production -f deployment/docker-compose.production.yml --profile migrate run --rm migrate
docker compose --env-file .env.production -f deployment/docker-compose.production.yml up -d web worker
```

## État du projet

AfriBounty est une base de préproduction avancée. Les fournisseurs réels de stockage objet, paiement, e-mail, KYC, ticketing et identité restent désactivés ou sandboxés. Les tests de charge, la restauration PostgreSQL et objet, les RPO/RTO, le TLS du domaine final et un audit indépendant sont nécessaires avant un lancement public.

## Ce que le projet démontre

Ce projet met en évidence le développement backend Python, la sécurité applicative, l’authentification forte, l’intégrité des données, le durcissement Docker, la CI/CD et la préparation méthodique d’une préproduction.

## Sécurité

Ne jamais ajouter de secret réel, de fichier `.env`, de clé privée, de donnée de rapport ou de preuve à GitHub. Les intégrations externes doivent rester désactivées jusqu’à validation contractuelle, technique et opérationnelle.
