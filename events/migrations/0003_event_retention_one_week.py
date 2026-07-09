from django.db import migrations, models


def set_one_week_retention(apps, schema_editor):
    Event = apps.get_model("events", "Event")
    Event.objects.update(media_retention_days=7)


class Migration(migrations.Migration):

    dependencies = [
        ("events", "0002_event_type_model"),
    ]

    operations = [
        migrations.AlterField(
            model_name="event",
            name="media_retention_days",
            field=models.PositiveIntegerField(default=7),
        ),
        migrations.RunPython(set_one_week_retention, migrations.RunPython.noop),
    ]
