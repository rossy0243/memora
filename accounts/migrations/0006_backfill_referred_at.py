from django.db import migrations
from django.db.models import F


def backfill_referred_at(apps, schema_editor):
    """Fait demarrer l'affiliation des filleuls existants a leur inscription.

    Sans cela, `referred_at` resterait vide et l'affiliation repartirait a zero
    au deploiement : des parrainages anciens seraient prolonges d'un an.
    """
    OrganizerProfile = apps.get_model("accounts", "OrganizerProfile")
    OrganizerProfile.objects.filter(
        referred_by__isnull=False, referred_at__isnull=True
    ).update(referred_at=F("created_at"))


def clear_referred_at(apps, schema_editor):
    OrganizerProfile = apps.get_model("accounts", "OrganizerProfile")
    OrganizerProfile.objects.update(referred_at=None)


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0005_organizerprofile_referred_at_payoutrequest_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_referred_at, clear_referred_at),
    ]
