# Étapes 21 à 28 — Sécurité transversale et observabilité

## Défenses HTTP

Les réponses applicatives portent une politique CSP restrictive, `nosniff`, une politique de permissions désactivant caméra/microphone/géolocalisation et une isolation d’origine. La configuration de proxy doit préserver HTTPS et ne faire confiance aux en-têtes transférés que lorsqu’ils proviennent du proxy d’infrastructure approuvé.

| Contrôle | Règle |
|---|---|
| CSP | Autoriser uniquement les sources strictement nécessaires ; pas d’exécution inline sans décision explicite. |
| Cookies | `HttpOnly`, `Secure` en production et `SameSite=Lax` au minimum. |
| CSRF/CORS | Origines explicites seulement ; aucun joker en production. |
| En-têtes | `nosniff`, `frame-ancestors 'none'`, politique de permissions restrictive. |

## Audit et corrélation

Chaque action de sécurité crée un événement append-only comportant une action, une ressource, un acteur de référence, une corrélation et une empreinte d’intégrité. Les données de preuve, secrets et corps de requête ne sont pas placés dans ces événements. Une modification ou suppression ordinaire est refusée par le modèle.

## Santé et métriques

Les endpoints de santé ne divulguent ni version détaillée, ni URL, ni compte, ni secret. Les métriques se limitent à une structure de service et à un indicateur indiquant l’absence de donnée sensible. Les tableaux de bord réels, seuils et alertes seront configurés par l’infrastructure à partir de ces contrats.

## Rétention et limitation

La rétention anonymise le contenu arrivé à échéance et ajoute un audit ; elle ne détruit pas l’historique de décision. Le limiteur de production utilise une opération Redis atomique `INCR`/`EXPIRE`. Le repli mémoire est techniquement autorisé seulement par le profil `test`; hors test, son activation ou l’absence de client Redis provoque un échec explicite plutôt qu’un fallback silencieux.

## Gel de sécurité et notifications

Un gel bloque les actions du sujet et impose une revue humaine. Les notifications transmettent une référence non sensible, jamais un token, un mot de passe, une preuve ou le contenu d’un rapport.
