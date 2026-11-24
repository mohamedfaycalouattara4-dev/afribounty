from django.db import migrations, models
import apps.reports.models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("reports", "0006_reportconversation_reportmessage"),
    ]

    operations = [
        migrations.CreateModel(
            name="ReportEvidence",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("category", models.CharField(choices=[("reproduction", "Reproduction"), ("impact", "Impact"), ("remediation", "Remédiation")], default="reproduction", max_length=24)),
                ("original_name", models.CharField(max_length=180)),
                ("content_type", models.CharField(max_length=100)),
                ("byte_size", models.PositiveIntegerField()),
                ("sha256", models.CharField(max_length=64)),
                ("artifact", models.FileField(upload_to=apps.reports.models.report_evidence_upload_path)),
                ("idempotency_key", models.CharField(max_length=96)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("report", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="evidence_items", to="reports.report")),
                ("uploaded_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="uploaded_report_evidence", to="identity.user")),
            ],
            options={"ordering": ["created_at", "id"]},
        ),
        migrations.AddConstraint(
            model_name="reportevidence",
            constraint=models.UniqueConstraint(fields=("report", "uploaded_by", "idempotency_key"), name="unique_report_evidence_idempotency"),
        ),
    ]
