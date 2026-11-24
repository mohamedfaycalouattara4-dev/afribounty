# Authentification locale AfriBounty

## Objectif et périmètre

AfriBounty utilise une identité locale autonome. Aucun fournisseur Google, Facebook, OIDC, e-mail ou SMS n’est nécessaire pour créer un compte, se connecter ou récupérer un accès. L’adresse e-mail, lorsqu’elle existe dans les données métier historiques, n’est pas un identifiant d’authentification et ne sert pas à vérifier ou réinitialiser un compte.

Le dispositif combine un identifiant local, un mot de passe haché avec Argon2id en production, une ou plusieurs passkeys WebAuthn/FIDO2, des challenges courts conservés côté serveur et des codes de récupération à usage unique dont seuls les hachages sont persistés.

## Parcours d’inscription

L’utilisateur choisit son type de compte, un identifiant local de 3 à 48 caractères, son nom affiché, son pays et un mot de passe long. L’interface indique explicitement que le mot de passe ne peut pas être récupéré par e-mail et qu’aucun SMS ne sera envoyé. Deux cases de confirmation sont obligatoires : acceptation des règles et compréhension de la récupération hors ligne.

Le compte est ensuite créé localement. Le mot de passe est validé par Django et stocké par `set_password`, avec Argon2id placé en tête de la politique de hachage de production. Une passkey est immédiatement demandée. La cérémonie WebAuthn exige une vérification locale de l’utilisateur et le serveur valide le challenge, l’origine HTTPS, l’identifiant RP, la présence de l’utilisateur et la signature d’attestation.

Après la passkey, dix codes de récupération sont affichés une seule fois. L’utilisateur doit confirmer qu’il les a imprimés ou conservés dans un emplacement hors ligne sécurisé. AfriBounty ne les transmet pas et ne les affiche plus ensuite. Les codes sont stockés uniquement sous forme de hachage SHA-256 ; chaque code ne peut être consommé qu’une fois.

## Parcours de connexion

L’utilisateur saisit son identifiant local et son mot de passe. Les tentatives sont journalisées par identifiant haché, avec une limite de cinq échecs dans une fenêtre de quinze minutes. Les réponses d’échec restent génériques et ne révèlent pas si un compte existe.

Si une passkey active est enregistrée, une seconde page demande sa validation. La demande doit être confirmée sur l’appareil de l’utilisateur par biométrie, code PIN local ou clé FIDO2. Le serveur vérifie l’origine, le challenge à usage unique, le RP ID, le compte associé, la clé publique et le compteur anti-rejeu de l’authenticator. Une anomalie de compteur révoque la clé par précaution.

Aucune clé privée, empreinte digitale, image faciale ou code PIN n’est transmis au serveur. Les sessions Django sont renouvelées lors des changements d’étape et les sessions gérées peuvent être révoquées depuis les paramètres de sécurité.

## Parcours de récupération

L’utilisateur ouvre « Récupérer votre compte », saisit son identifiant, un code hors ligne et un nouveau mot de passe. Avant validation, l’interface avertit que le code sera consommé définitivement et que toutes les sessions existantes seront révoquées.

Après vérification atomique, le code est marqué comme consommé, les sessions actives sont révoquées, le mot de passe est remplacé et l’utilisateur doit enregistrer une nouvelle passkey. De nouveaux codes sont ensuite générés. Un ancien code réutilisé est rejeté.

Si tous les codes et toutes les passkeys sont perdus, il n’existe volontairement aucun contournement par e-mail ou SMS. Une procédure administrative séparée doit vérifier l’identité selon la politique de l’organisation. Pour les comptes administrateur, sécurité et finance, cette procédure doit être approuvée par deux personnes distinctes et être journalisée. Une récupération instantanée par un seul opérateur est interdite.

## Avertissements d’interface obligatoires

| Étape | Avertissement visible | Confirmation demandée |
|---|---|---|
| Inscription | Aucun e-mail ni SMS de récupération ; perte de tous les moyens potentiellement irrécupérable. | Règles acceptées et conséquence comprise. |
| Enregistrement passkey | Utiliser uniquement son appareil personnel ou sa clé FIDO2 ; ne jamais valider à la demande d’un tiers. | Bouton explicite avant la cérémonie cryptographique. |
| Affichage des codes | Affichage unique ; impression ou conservation hors ligne obligatoire ; ne jamais partager. | Case de sauvegarde sécurisée. |
| Connexion passkey | Vérifier le domaine et annuler toute fenêtre non sollicitée. | Bouton explicite avant la demande d’authenticator. |
| Récupération | Consommation irréversible du code et révocation de toutes les sessions. | Case de compréhension avant soumission. |
| Révocation de session | La session devient immédiatement inutilisable et l’action n’est pas annulable. | Action POST protégée par CSRF. |

## Contrôles techniques livrés

Les routes passwordless historiques sont désactivées avec un statut HTTP `410 Gone`. Les fonctions et modèles historiques restent conservés uniquement pour compatibilité de migration et de données anciennes ; ils ne sont plus raccordés à l’interface d’accès. Les nouveaux parcours ne déclenchent aucun envoi de message.

La production impose une origine WebAuthn HTTPS et un RP ID correspondant au domaine final. Les options WebAuthn sont produites par la bibliothèque spécialisée `webauthn==3.0.0` et ne sont jamais fabriquées par concaténation manuelle dans le navigateur. Le JavaScript de cérémonie est servi comme fichier statique compatible avec la CSP stricte.

## Validation

La suite de tests couvre la création locale sans e-mail, le hachage des codes, la consommation unique, la révocation de sessions, la limitation des mots de passe, la création de challenges WebAuthn, l’absence d’écrans e-mail, les avertissements et la désactivation de l’ancienne route. Les contrôles de qualité doivent inclure les tests Django, Ruff, le formatage, `node --check` sur le JavaScript et `manage.py makemigrations --check --dry-run`.

La conformité opérationnelle finale nécessite encore un test sur domaine HTTPS réel avec au moins deux authenticator compatibles, une préproduction PostgreSQL/Redis, des tests de restauration et une revue de sécurité indépendante. Aucun dépôt ne peut prouver seul la sécurité absolue de l’environnement d’exploitation.
