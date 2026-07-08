import django.db.models.deletion
from django.db import migrations, models


DEFAULT_EVENT_TYPES = [
    ("wedding", "Mariage", 1),
    ("birthday", "Anniversaire", 2),
    ("corporate", "Evenement professionnel", 3),
    ("other", "Autre", 99),
]


def create_event_types_and_link_events(apps, schema_editor):
    Event = apps.get_model("events", "Event")
    EventType = apps.get_model("events", "EventType")

    event_types = {}
    for code, label, sort_order in DEFAULT_EVENT_TYPES:
        event_type, _ = EventType.objects.get_or_create(
            code=code,
            defaults={
                "label": label,
                "sort_order": sort_order,
                "is_active": True,
            },
        )
        event_types[code] = event_type

    fallback = event_types["other"]
    for event in Event.objects.all():
        event.event_type = event_types.get(event.legacy_event_type, fallback)
        event.save(update_fields=["event_type"])


class Migration(migrations.Migration):

    dependencies = [
        ("events", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="EventType",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.SlugField(max_length=40, unique=True)),
                ("label", models.CharField(max_length=80)),
                ("sort_order", models.PositiveSmallIntegerField(default=0)),
                ("is_active", models.BooleanField(default=True)),
            ],
            options={
                "ordering": ["sort_order", "label"],
                "verbose_name": "type d'evenement",
                "verbose_name_plural": "types d'evenements",
            },
        ),
        migrations.RenameField(
            model_name="event",
            old_name="event_type",
            new_name="legacy_event_type",
        ),
        migrations.AddField(
            model_name="event",
            name="event_type",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="events",
                to="events.eventtype",
            ),
        ),
        migrations.RunPython(create_event_types_and_link_events, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="event",
            name="event_type",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="events",
                to="events.eventtype",
            ),
        ),
        migrations.RemoveField(
            model_name="event",
            name="legacy_event_type",
        ),
    ]
