from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = [("organizations", "0001_initial")]
    operations = [
        migrations.CreateModel(
            name="Program",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=180)),
                ("status", models.CharField(choices=[("draft", "Brouillon"), ("private_active", "Privé actif"), ("suspended", "Suspendu"), ("closed", "Fermé")], default="draft", max_length=20)),
                ("policy_version", models.CharField(max_length=40)),
                ("policy_hash", models.CharField(max_length=128)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="programs", to="organizations.organization")),
            ],
            options={"constraints": [models.UniqueConstraint(fields=("organization", "name"), name="unique_program_name_per_organization")]},
        ),
        migrations.CreateModel(
            name="AssetScope",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("asset", models.CharField(max_length=255)),
                ("asset_type", models.CharField(choices=[("web", "Application web"), ("api", "API"), ("mobile", "Application mobile")], default="web", max_length=16)),
                ("is_active", models.BooleanField(default=True)),
                ("is_verified", models.BooleanField(default=False)),
                ("is_excluded", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("program", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="scopes", to="programs.program")),
            ],
            options={"constraints": [models.UniqueConstraint(fields=("program", "asset"), name="unique_asset_scope_per_program")]},
        ),
    ]
