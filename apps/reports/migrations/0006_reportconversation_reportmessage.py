from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("reports", "0005_report_submission_content"),
    ]

    operations = [
        migrations.CreateModel(
            name="ReportConversation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("report", models.OneToOneField(on_delete=models.PROTECT, related_name="conversation", to="reports.report")),
            ],
        ),
        migrations.CreateModel(
            name="ReportMessage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("body", models.TextField()),
                ("idempotency_key", models.CharField(max_length=96)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("author", models.ForeignKey(on_delete=models.PROTECT, related_name="report_messages", to=settings.AUTH_USER_MODEL)),
                ("conversation", models.ForeignKey(on_delete=models.PROTECT, related_name="messages", to="reports.reportconversation")),
            ],
            options={"ordering": ["created_at", "id"]},
        ),
        migrations.AddConstraint(
            model_name="reportmessage",
            constraint=models.UniqueConstraint(fields=("conversation", "author", "idempotency_key"), name="unique_report_message_idempotency"),
        ),
    ]
