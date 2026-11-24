import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("identity", "0002_accountprofile_passwordlessaccesstoken"),
    ]

    operations = [
        migrations.CreateModel(
            name="AccountPrivacyPreference",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("retention_days", models.PositiveIntegerField(default=365)),
                ("exports_enabled", models.BooleanField(default=False)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="privacy_preference", to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
