from django.db import migrations, models


def generate_access_keys(apps, schema_editor):
    import secrets

    from django.db.models import Q

    Event = apps.get_model("events", "Event")

    for event in Event.objects.filter(Q(public_access_key__isnull=True) | Q(public_access_key="")):
        while True:
            key = secrets.token_urlsafe(12).replace("_", "-")
            if not Event.objects.filter(public_access_key=key).exists():
                event.public_access_key = key
                event.save(update_fields=["public_access_key"])
                break


class Migration(migrations.Migration):

    dependencies = [
        ("events", "0003_event_retention_one_week"),
    ]

    operations = [
        migrations.AddField(
            model_name="event",
            name="public_access_key",
            field=models.CharField(blank=True, max_length=32, null=True),
        ),
        migrations.RunPython(generate_access_keys, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="event",
            name="public_access_key",
            field=models.SlugField(blank=True, max_length=32, unique=True),
        ),
    ]
