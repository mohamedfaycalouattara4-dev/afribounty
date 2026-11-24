from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("identity", "0003_accountprivacypreference")]

    operations = [
        migrations.CreateModel(
            name="AccountDataRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("request_type", models.CharField(choices=[("export", "Export de données"), ("erasure", "Effacement contrôlé")], max_length=16)),
                ("state", models.CharField(choices=[("requested", "Demandée"), ("cancelled", "Annulée"), ("completed", "Traitée")], default="requested", max_length=16)),
                ("requested_at", models.DateTimeField(auto_now_add=True)),
                ("cancelled_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("local_summary", models.JSONField(default=dict)),
                ("user", models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="data_rights_requests", to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
