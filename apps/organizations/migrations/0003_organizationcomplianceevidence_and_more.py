from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("organizations", "0002_organization_exports_enabled_and_more")]
    operations = [
        migrations.CreateModel(name="OrganizationComplianceEvidence", fields=[("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")), ("label", models.CharField(max_length=120)), ("local_reference", models.CharField(max_length=255)), ("status", models.CharField(default="submitted", max_length=24)), ("created_at", models.DateTimeField(auto_now_add=True)), ("organization", models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="compliance_evidence", to="organizations.organization")), ("submitted_by", models.ForeignKey(on_delete=models.deletion.PROTECT, to=settings.AUTH_USER_MODEL))]),
        migrations.CreateModel(name="OrganizationComplianceRequest", fields=[("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")), ("message", models.TextField()), ("resolved_at", models.DateTimeField(blank=True, null=True)), ("created_at", models.DateTimeField(auto_now_add=True)), ("organization", models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="compliance_requests", to="organizations.organization")), ("requested_by", models.ForeignKey(on_delete=models.deletion.PROTECT, to=settings.AUTH_USER_MODEL))]),
    ]
