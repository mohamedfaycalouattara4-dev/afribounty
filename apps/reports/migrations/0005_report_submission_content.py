from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("reports", "0004_reportdraft")]

    operations = [
        migrations.AddField(model_name="report", name="impact", field=models.TextField(default="")),
        migrations.AddField(model_name="report", name="reproduction", field=models.TextField(default="")),
        migrations.AddField(model_name="report", name="proposed_severity", field=models.CharField(blank=True, default="", max_length=20)),
    ]
