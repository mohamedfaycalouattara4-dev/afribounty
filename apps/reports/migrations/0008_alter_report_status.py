from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("reports", "0007_reportevidence"),
    ]

    operations = [
        migrations.AlterField(
            model_name="report",
            name="status",
            field=models.CharField(
                choices=[
                    ("submitted", "Soumis"),
                    ("in_triage", "En triage"),
                    ("information_required", "Information requise"),
                    ("valid", "Validé"),
                    ("out_of_scope", "Hors périmètre"),
                    ("duplicate", "Doublon"),
                    ("non_reproducible", "Non reproductible"),
                    ("remediation", "En remédiation"),
                    ("resolved", "Résolu"),
                    ("disclosure_review", "Divulgation en revue"),
                ],
                default="submitted",
                max_length=32,
            ),
        )
    ]
