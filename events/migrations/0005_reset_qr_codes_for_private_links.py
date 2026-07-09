from django.db import migrations


def reset_qr_codes(apps, schema_editor):
    Event = apps.get_model("events", "Event")
    Event.objects.exclude(qr_code_image="").update(qr_code_image="")


class Migration(migrations.Migration):

    dependencies = [
        ("events", "0004_event_public_access_key"),
    ]

    operations = [
        migrations.RunPython(reset_qr_codes, migrations.RunPython.noop),
    ]
