# Étape 29 — Runbook incident et accès d’urgence

## Déclenchement

Le runbook est activé en cas de suspicion de compte compromis, exposition de secret, accès inter-organisation, défaillance du contrôle de scope, anomalie de paiement future, fuite de preuve ou activité de laboratoire hors de son isolement prévu. Le premier objectif est de réduire le risque sans détruire les traces.

| Phase | Action | Preuve attendue |
|---|---|---|
| Triage | Ouvrir un incident, horodater, classer l’impact et désigner un responsable. | Identifiant d’incident et journal initial. |
| Contention | Geler le compte, suspendre le programme ou arrêter la file affectée selon le moindre impact. | Événement d’audit et décision motivée. |
| Préservation | Conserver logs, événements, configuration et indicateurs sans recopier de secrets. | Liste des sources et hash/horodatage. |
| Investigation | Examiner la chronologie, la corrélation et l’étendue ; séparer faits et hypothèses. | Compte rendu factuel. |
| Correction | Corriger, faire relire, tester et surveiller la reprise. | Changement lié aux tests. |
| Communication | Informer seulement les rôles, organisations et autorités requis par le contrat et la loi. | Journal des communications. |
| Clôture | Réaliser une revue post-incident et mettre à jour modèle de menace, tests et runbook. | Actions suivies avec propriétaire et échéance. |

## Accès d’urgence

L’accès d’urgence est temporaire, justifié, limité à un périmètre, approuvé par deux personnes distinctes quand l’urgence le permet, journalisé et révoqué dès la fin de l’intervention. Il n’autorise pas l’export de preuves ni la divulgation hors procédure.

## Exercice de table-top

Scénario : un sujet tente des actions répétées hors comportement attendu. L’équipe déclenche le gel, vérifie les événements corrélés, rédige une notification non sensible, valide que la rétention préserve l’audit, puis clôture l’exercice. Le procès-verbal doit noter les décisions, lacunes et actions de correction.
