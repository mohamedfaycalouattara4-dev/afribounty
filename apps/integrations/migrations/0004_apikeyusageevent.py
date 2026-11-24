from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("integrations", "0003_supportcasereply")]

    operations = [
        migrations.CreateModel(
            name="ApiKeyUsageEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("scope", models.CharField(max_length=96)),
                ("safe_reference", models.CharField(max_length=128)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("key", models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="usage_events", to="integrations.apikey")),
            ],
        ),
    ]
