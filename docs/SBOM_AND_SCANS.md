# SBOM locale et contrôles de chaîne d’approvisionnement

| Composant | Version verrouillée | Rôle |
|---|---:|---|
| Django | 5.2.17 | Framework applicatif |
| Django REST Framework | 3.16.1 | APIs internes/futures |
| Celery | 5.5.3 | Tâches asynchrones |
| Redis | 6.1.0 | Cache, broker et limites |
| psycopg binary | 3.2.9 | PostgreSQL production |
| Uvicorn | 0.35.0 | Serveur ASGI |
| Gunicorn | 23.0.0 | Processus applicatif |
| cryptography | 50.0.0 | Chiffrement TOTP et signatures |

Les contrôles locaux exécutés avant livraison sont `ruff check`, `ruff format --check`, `pip-audit -r requirements.lock`, le scan de motifs de secrets et le vérificateur ZIP. Ils ne remplacent pas une surveillance CVE continue après déploiement.
