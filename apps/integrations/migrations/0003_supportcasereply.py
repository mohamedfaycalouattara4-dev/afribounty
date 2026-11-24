from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("integrations", "0002_localnotification")]

    operations = [
        migrations.CreateModel(
            name="SupportCaseReply",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("sanitized_message", models.TextField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("author", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="support_replies", to="identity.user")),
                ("case", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="replies", to="integrations.supportcase")),
            ],
            options={"ordering": ["created_at", "id"]},
        )
    ]
