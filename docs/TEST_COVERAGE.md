# Rapport de couverture locale

| Mesure | Résultat réel |
|---|---:|
| Commande | `coverage run --source=apps manage.py test tests` |
| Tests exécutés | 56 réussis |
| Couverture agrégée des applications | **93 %** |
| Exclusions justifiées | Migrations, adaptateurs de production non fournis, fournisseurs externes et opérations réelles hors sandbox. |

La mesure a été exécutée localement sur SQLite avec les profils de test. Les zones les moins couvertes concernent surtout les branches défensives, les intégrations qui exigeraient un service réel et les opérations interdites dans ce ZIP. Toute baisse sous 90 % des applications doit être explicitement examinée avant préproduction.
