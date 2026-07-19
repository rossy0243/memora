from django.db import migrations


def accent_labels(apps, schema_editor):
    EventType = apps.get_model("events", "EventType")
    EventType.objects.filter(code="corporate", label="Evenement professionnel").update(
        label="Événement professionnel"
    )


def unaccent_labels(apps, schema_editor):
    EventType = apps.get_model("events", "EventType")
    EventType.objects.filter(code="corporate", label="Événement professionnel").update(
        label="Evenement professionnel"
    )


class Migration(migrations.Migration):

    dependencies = [
        ("events", "0008_alter_event_price_amount_alter_event_price_currency"),
    ]

    operations = [
        migrations.RunPython(accent_labels, unaccent_labels),
    ]
