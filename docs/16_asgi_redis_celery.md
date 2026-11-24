# Étapes 14 à 16 — Redis privé, Celery et ASGI

## Démarrage attendu en environnement contrôlé

Redis et PostgreSQL doivent être des services privés, non exposés à Internet. Django communique avec PostgreSQL ; Redis sert au cache et au broker Celery ; les workers Celery sont des processus distincts de l’ASGI. Nginx ou un proxy équivalent termine TLS et transmet les en-têtes nécessaires à Django.

| Processus | Commande de référence | Règle de sécurité |
|---|---|---|
| ASGI | `uvicorn config.asgi:application --host 127.0.0.1 --port 8000` | Écoute locale derrière proxy ; pas d’exposition directe de développement. |
| Worker Celery | `celery -A config worker --loglevel=INFO` | Compte de service dédié, accès minimal, journalisation structurée. |
| PostgreSQL | Service privé managé ou auto-administré. | Utilisateur applicatif sans privilèges d’administration globale. |
| Redis | Service privé protégé par réseau et authentification. | Jamais exposé au web ; base séparée ou préfixes par environnement. |

## Test de connectivité à exécuter chez le porteur de projet

Une fois PostgreSQL et Redis disponibles dans un réseau privé, exécutez les commandes suivantes depuis l’environnement d’intégration, avec secrets injectés hors dépôt :

```bash
python manage.py migrate
python manage.py shell -c "from django.db import connection; connection.ensure_connection(); print('postgres: ok')"
celery -A config inspect ping
```

L’échec de connexion doit bloquer le passage à la préproduction. Ne remplacez jamais un échec par un fallback silencieux sur SQLite ou un Redis public.
