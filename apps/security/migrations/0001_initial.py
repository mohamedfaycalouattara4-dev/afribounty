from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="AuditEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("occurred_at", models.DateTimeField(auto_now_add=True)),
                ("actor_reference", models.CharField(blank=True, max_length=128)),
                ("action", models.CharField(max_length=96)),
                ("resource_type", models.CharField(max_length=96)),
                ("resource_reference", models.CharField(max_length=128)),
                ("correlation_id", models.CharField(db_index=True, max_length=128)),
                ("metadata", models.JSONField(default=dict)),
                ("event_nonce", models.CharField(max_length=32, unique=True)),
                ("integrity_hash", models.CharField(max_length=64, unique=True)),
            ],
            options={"ordering": ["id"]},
        ),
        migrations.CreateModel(
            name="RetentionRecord",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("category", models.CharField(max_length=64)),
                ("subject_reference", models.CharField(max_length=128)),
                ("payload", models.JSONField(default=dict)),
                ("expires_at", models.DateTimeField()),
                ("anonymized_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
        ),
        migrations.CreateModel(
            name="SecuritySubject",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("reference", models.CharField(max_length=128, unique=True)),
                ("status", models.CharField(choices=[("active", "Actif"), ("frozen", "Gelé")], default="active", max_length=16)),
                ("frozen_reason", models.CharField(blank=True, max_length=240)),
                ("frozen_at", models.DateTimeField(blank=True, null=True)),
                ("review_required", models.BooleanField(default=False)),
            ],
        ),
    ]
