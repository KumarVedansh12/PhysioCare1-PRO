from django.db import migrations


OLD_BODY = "You can book Saturday clinic and video consultations until 6:00 PM through the appointment portal."
NEW_BODY = "You can book Saturday in-clinic consultations until 6:00 PM through the appointment portal."


def update_demo_announcement(apps, schema_editor):
    CMSContent = apps.get_model("core", "CMSContent")
    CMSContent.objects.filter(
        title="Clinic hours extended on Saturdays",
        body=OLD_BODY,
    ).update(body=NEW_BODY)


class Migration(migrations.Migration):
    dependencies = [("core", "0008_alter_appointment_mode")]
    operations = [
        migrations.RunPython(update_demo_announcement, migrations.RunPython.noop)
    ]
