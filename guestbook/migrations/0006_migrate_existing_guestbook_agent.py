"""Reprend l'ancienne affectation mono-agent (Event.guestbook_agent) sous
forme de GuestBookAssignment, avant qu'events.0015 ne supprime ces champs.
"""
from django.db import migrations


def migrate_forward(apps, schema_editor):
    Event = apps.get_model("events", "Event")
    GuestBookAssignment = apps.get_model("guestbook", "GuestBookAssignment")

    events = Event.objects.filter(guestbook_agent__isnull=False)
    for event in events:
        GuestBookAssignment.objects.get_or_create(
            event=event,
            agent_id=event.guestbook_agent_id,
            defaults={
                "started_at": event.guestbook_started_at,
                "ended_at": event.guestbook_ended_at,
            },
        )


def migrate_backward(apps, schema_editor):
    # Rien a restaurer : events.0015 (qui recree les champs) initialise a NULL.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("guestbook", "0005_guestbookassignment"),
        ("events", "0014_event_selected_music_track"),
    ]

    operations = [
        migrations.RunPython(migrate_forward, migrate_backward),
    ]
