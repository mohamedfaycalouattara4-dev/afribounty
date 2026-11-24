# Variables d’environnement et secrets

Les secrets sont injectés uniquement au moment de l’exécution par le gestionnaire de secrets de l’environnement. Le fichier `.env.production.example` livré à titre de contrat ne contient que des chaînes d’instructions non utilisables ; il ne doit jamais être copié tel quel en production ni recevoir de valeur réelle dans le dépôt.

| Variable | Utilité | Règle |
|---|---|---|
| `DJANGO_SETTINGS_MODULE` | Sélectionne développement, test ou production. | Valeur contrôlée par l’environnement d’exécution. |
| `DJANGO_SECRET_KEY` | Signature Django. | Secret long, aléatoire, distinct par environnement et fourni par gestionnaire de secrets. |
| `DJANGO_ALLOWED_HOSTS` | Hôtes HTTP autorisés. | Liste explicite en production ; aucun joker ni hôte local. |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | Origines CSRF autorisées. | Origines HTTPS explicites uniquement en production. |
| `DJANGO_DATABASE_URL` | Connexion PostgreSQL. | URL hors dépôt ; utilisateur à privilèges minimaux ; TLS recommandé. |
| `DJANGO_REDIS_URL` | Cache et broker Celery. | Redis privé, authentifié et isolé du web ; TLS recommandé. |
| `IDENTITY_TOTP_FERNET_KEY` | Chiffrement des éléments TOTP. | Clé Fernet valide, distincte par environnement, rotation documentée. |
| `EVIDENCE_ENCRYPTION_KEY` | Chiffrement des preuves. | Clé Fernet valide, distincte des autres clés, rotation et sauvegarde contrôlées. |
| `METRICS_AUTH_TOKEN` | Protection de l’observabilité. | Jeton aléatoire distinct, d’au moins 32 caractères. |
| `AUDIT_INTEGRITY_KEY` | Signature des journaux d’audit. | Clé distincte, aléatoire, d’au moins 32 caractères. |
| `DJANGO_EMAIL_BACKEND` | Envoi transactionnel. | Fournisseur choisi et testé uniquement en environnement contrôlé. |
| `POSTGRES_PASSWORD` | Mot de passe de la base de préproduction Compose. | Secret hors dépôt, jamais repris dans une commande publique. |
| `REDIS_PASSWORD` | Mot de passe Redis de préproduction Compose. | Secret hors dépôt, jamais repris dans une commande publique. |
| `DJANGO_LOG_LEVEL` | Niveau de journalisation. | `INFO` par défaut ; aucun contenu sensible dans les logs. |

## Chargement sûr

L’équipe d’infrastructure copie le gabarit hors du dépôt, remplace uniquement les valeurs dans le coffre de secrets ou le fichier local ignoré, puis lance les contrôles de configuration. Le script `scripts/generate_production_secrets.py` peut produire des valeurs aléatoires sur la sortie standard ; il ne crée aucun fichier et sa sortie ne doit pas être enregistrée dans Git, les logs CI ou les tickets.

Toute valeur réelle doit être renouvelable sans modification du code. Les rotations de clés doivent être planifiées avec une procédure de compatibilité, de révocation et de restauration testée. Un fichier local de développement reste ignoré par Git et n’est jamais ajouté à une archive de livraison.
