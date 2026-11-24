# Politique de sécurité AfriBounty

## Signaler une vulnérabilité

Ne publiez pas une vulnérabilité dans une issue publique. Transmettez une description minimale, les étapes de reproduction non destructives, l’impact observé et une preuve expurgée au canal de sécurité désigné par l’équipe AfriBounty. N’incluez jamais de secret, de donnée personnelle, de preuve réelle ou de cible non autorisée.

L’équipe accuse réception, qualifie le risque, gèle si nécessaire la fonctionnalité concernée et documente la correction. Un retest indépendant est requis pour les vulnérabilités élevées ou critiques avant réouverture du flux.

## Règles d’intervention

Les tests doivent être limités à des programmes explicitement autorisés, à des environnements de préproduction ou aux laboratoires sandboxés de la plate-forme. Toute cible externe non déclarée, tout déni de service, toute exfiltration et toute tentative d’accès à des données réelles sont interdits.

## Critères de livraison sécurité

| Contrôle | Exigence |
|---|---|
| Tests et régression | Les tests Django, migrations, lint et formatage doivent être verts. |
| Dépendances | L’audit de dépendances ne doit signaler aucune vulnérabilité non acceptée. |
| Secrets | Aucun secret réel, fichier `.env`, bytecode ou base locale dans la release. |
| Preuves | Les pièces restent privées, chiffrées selon la configuration et non publiées par URL directe. |
| Production | PostgreSQL, Redis, TLS, stockage objet privé et fournisseurs sont validés dans une préproduction contrôlée. |
| Go/no-go | La décision est humaine, datée et tracée ; un statut local ne constitue jamais une autorisation d’ouverture. |
