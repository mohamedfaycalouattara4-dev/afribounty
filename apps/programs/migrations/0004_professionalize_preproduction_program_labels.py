from django.db import migrations


def professionalize_preproduction_program_labels(apps, schema_editor):
    Program = apps.get_model("programs", "Program")
    Program.objects.filter(name="Programme public de démonstration", policy_version="demo-v1").update(
        name="Programme de préproduction AfriBounty",
        policy_version="preproduction-v1",
    )


def restore_legacy_preproduction_program_labels(apps, schema_editor):
    Program = apps.get_model("programs", "Program")
    Program.objects.filter(name="Programme de préproduction AfriBounty", policy_version="preproduction-v1").update(
        name="Programme public de démonstration",
        policy_version="demo-v1",
    )


class Migration(migrations.Migration):
    dependencies = [("programs", "0003_programinvitation_rules_accepted_at")]

    operations = [migrations.RunPython(professionalize_preproduction_program_labels, restore_legacy_preproduction_program_labels)]
