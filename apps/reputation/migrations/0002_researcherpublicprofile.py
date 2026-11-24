from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("reputation", "0001_initial")]

    operations = [
        migrations.CreateModel(
            name="ResearcherPublicProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("public_alias", models.CharField(max_length=80)),
                ("opted_in", models.BooleanField(default=False)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.OneToOneField(on_delete=models.deletion.CASCADE, related_name="public_researcher_profile", to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
