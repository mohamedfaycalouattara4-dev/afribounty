# Matrice ASVS applicable — état local

Cette matrice relie les contrôles applicables aux preuves locales. Elle ne constitue pas une certification et ne remplace pas une revue humaine sur préproduction. Référence : [OWASP ASVS](https://owasp.org/www-project-application-security-verification-standard/).

| Domaine | Contrôle AfriBounty | Preuve locale | État |
|---|---|---|---|
| Authentification | Vérification d’e-mail, TOTP chiffré, WebAuthn, récupération contrôlée. | Tests identité/MFA. | Couvert localement |
| Session et accès | Sessions gérées, révocation, step-up MFA et RBAC. | Tests identité, récompense et API. | Couvert localement |
| Autorisation | Isolation organisationnelle, conflits, consoles triage/finance séparées. | Tests multi-tenant et HTTP. | Couvert localement |
| Entrées | Validation de transitions, scope, brouillon et payloads signés. | Tests rapports, intégrations et webhooks. | Couvert localement |
| Données sensibles | TOTP chiffré, masquage support, exports agrégés. | Tests Académie, support et exports. | Couvert localement |
| Journalisation | Audit append-only, corrélation et traces de décision. | Tests sécurité et préparation. | Couvert localement |
| Configuration | Réglages production, secrets obligatoires, dépendances verrouillées. | Tests settings et audit de dépendances. | Couvert localement |
| Déploiement | Reverse proxy, TLS réel, headers réseau et secrets de production. | Revue préproduction requise. | Externe requis |
