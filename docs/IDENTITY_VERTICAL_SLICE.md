# Tranche verticale 1 — Identité, rôles et onboarding AfriBounty

## But

Livrer un parcours visible et utilisable qui permet à une personne de choisir son intention, de demander un accès sans mot de passe, de vérifier son e-mail via un lien temporaire et de terminer un onboarding adapté. Cette tranche ne déclenche aucun paiement, aucune vérification légale automatique et aucune ouverture de programme.

| Parcours | Données minimales | État après validation | Limites initiales |
|---|---|---|---|
| Chercheur | Nom affiché, e-mail, pays, acceptation règles. | Profil chercheur, e-mail vérifié, dashboard chercheur. | MFA et paiement restent des étapes de sécurité distinctes. |
| Organisation | Nom affiché, e-mail responsable, nom organisation, pays, acceptation règles. | Organisation en attente de vérification et responsable propriétaire. | Aucun programme public/privé n’est créé automatiquement. |
| Membre d’équipe | À ajouter après invitations organisationnelles visibles. | Non couvert par cette tranche. | Invitation obligatoire. |

## Sécurité

Le flux est sans mot de passe : les jetons de vérification et de connexion sont stockés seulement sous forme de hash, à usage unique et à expiration courte. La confirmation est uniforme afin de ne pas révéler l’existence d’un e-mail. Les actions sensibles restent protégées par MFA/step-up dans les blocs suivants. Aucun jeton ne doit être affiché au navigateur, journalisé ou envoyé hors du canal e-mail prévu.

## Critères de fin

Les écrans d’inscription, demande de connexion, vérification, déconnexion, choix de rôle et onboarding sont rendus. Les permissions et les redirections sont testées. Les parcours sont vérifiés sur l’instance locale ; l’envoi d’e-mail demeure local/sandbox tant qu’un fournisseur transactionnel réel n’est pas explicitement configuré.
