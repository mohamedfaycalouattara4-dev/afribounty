from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("integrations", "0004_apikeyusageevent")]

    operations = [migrations.AddField(model_name="localnotification", name="archived_at", field=models.DateTimeField(blank=True, null=True))]
