# AfriBounty — Écrans, accessibilité et parcours des étapes 121 à 130

## Routes livrées

| Route | Public visé | Contrôle d’accès | Données exposées |
|---|---|---|---|
| `/` | Public | Aucune session | Programmes publics, pages de confiance et navigation. |
| `/onboarding/researcher/` | Chercheur connecté | Session Django | Étapes de prise en main, sans donnée de rapport tiers. |
| `/dashboard/researcher/` | Chercheur | Session Django | Ses propres rapports, réputation et état éthique. |
| `/reports/draft/<program_id>/` | Chercheur | Session Django et appartenance programme | Son unique brouillon lié au programme. |
| `/dashboard/organization/<organization_id>/` | Membre organisation | Appartenance sans conflit actif | Programmes, compteurs, membres. |
| `/console/triage/` | Triager | Permission de triage | File de triage. |
| `/console/finance/` | Finance | Permission de récompense | Récompenses, sans preuve ni rapport détaillé. |
| `/academy/` | Apprenant | Session Django | Laboratoires seulement après acceptation éthique et challenges isolés. |

## Design system et règles d’accessibilité

Le langage est français, l’interface est pensée mobile-first et utilise une structure sémantique : lien d’évitement, en-tête, navigation, contenu principal et pied de page. Les champs ont des libellés explicites et les alertes utilisent un statut accessible. Les liens et contrôles reçoivent un focus visible épais ; la palette emploie un fond très clair, un texte bleu très sombre et des actions indigo afin de maintenir un contraste élevé.

Les composants documentés sont la navigation, le bouton, le champ de formulaire, l’alerte, la carte de donnée, le tableau avec légende et l’état vide. Les grilles passent à une seule colonne sous 720 pixels et aucune information critique n’est transmise par la couleur seule. Les parcours sensibles restent protégés au serveur ; la visibilité d’un écran ne remplace jamais son contrôle d’autorisation.
