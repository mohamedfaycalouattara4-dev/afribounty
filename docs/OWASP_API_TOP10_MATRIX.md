# Matrice OWASP API Top 10 — état local

Référence : [OWASP API Security Top 10](https://owasp.org/www-project-api-security/).

| Risque | Mesure AfriBounty | Preuve locale | État |
|---|---|---|---|
| Autorisation objet | Filtrage par chercheur, organisation, invitation et rôle. | Tests dashboards, organisations et programmes. | Couvert localement |
| Authentification | MFA, récupérations contrôlées, révocations. | Tests identité. | Couvert localement |
| Autorisation propriété | Scopes vérifiés, privé/public, arrêt d’urgence. | Tests programmes et soumission. | Couvert localement |
| Consommation de ressources | Limitation Redis/mémoire, plafonds notification et quotas labo. | Tests sécurité, intégrations et Académie. | Couvert localement |
| Fonctions sensibles | Double contrôle récompense, step-up bénéficiaire, consoles séparées. | Tests récompense et expérience. | Couvert localement |
| Flux métier | États de rapport, triage, médiation, idempotence et compensation. | Tests rapports, triage et paiements. | Couvert localement |
| SSRF/injections | Aucun client URL arbitraire, entrées contrôlées et sandbox sans cible tierce. | Revue de code locale. | À revoir en audit externe |
| Inventaire API | Routes santé et expérience documentées ; APIs externes sandboxées. | Documentation ZIP et tests HTTP. | Partiel |
| Mauvaise configuration | Gardes de production et scans de secrets. | Tests settings et contrôle ZIP. | Couvert localement |
| Consommation API tierce | Adaptateurs in-memory, signature webhook et anti-rejeu. | Tests intégrations et récompenses. | Couvert localement |
