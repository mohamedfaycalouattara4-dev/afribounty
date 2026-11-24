from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("organizations", "0001_initial"),
        ("programs", "0001_initial"),
    ]
    operations = [
        migrations.CreateModel(
            name="Report",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=240)),
                ("asset", models.CharField(max_length=255)),
                ("status", models.CharField(choices=[("submitted", "Soumis"), ("in_triage", "En triage"), ("information_required", "Information requise"), ("valid", "Valide"), ("out_of_scope", "Hors périmètre"), ("duplicate", "Doublon"), ("non_reproducible", "Non reproductible"), ("remediation", "En remédiation"), ("resolved", "Résolu"), ("disclosure_review", "Divulgation en revue")], default="submitted", max_length=32)),
                ("policy_version", models.CharField(max_length=40)),
                ("policy_hash", models.CharField(max_length=128)),
                ("idempotency_key", models.CharField(max_length=96)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("author", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="submitted_reports", to=settings.AUTH_USER_MODEL)),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="reports", to="organizations.organization")),
                ("program", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="reports", to="programs.program")),
            ],
            options={"constraints": [models.UniqueConstraint(fields=("program", "author", "idempotency_key"), name="unique_report_submission_idempotency")]},
        ),
        migrations.CreateModel(
            name="ReportEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("from_status", models.CharField(max_length=32)),
                ("to_status", models.CharField(max_length=32)),
                ("reason", models.CharField(max_length=500)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("actor", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="report_events", to=settings.AUTH_USER_MODEL)),
                ("report", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="events", to="reports.report")),
            ],
            options={"ordering": ["created_at", "id"]},
        ),
    ]
