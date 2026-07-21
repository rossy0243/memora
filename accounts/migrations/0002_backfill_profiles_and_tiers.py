import secrets

from django.db import migrations

REFERRAL_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

# Seuils par défaut (identiques à SiteConfiguration) pour ne pas dépendre de la config à la migration.
DEFAULT_TIER_MEDIUM_MIN = 51
DEFAULT_TIER_PREMIUM_MIN = 101


def tier_for_count(count):
    if count >= DEFAULT_TIER_PREMIUM_MIN:
        return "premium"
    if count >= DEFAULT_TIER_MEDIUM_MIN:
        return "medium"
    return "starter"


def backfill(apps, schema_editor):
    User = apps.get_model("auth", "User")
    OrganizerProfile = apps.get_model("accounts", "OrganizerProfile")
    Event = apps.get_model("events", "Event")

    existing_codes = set(OrganizerProfile.objects.values_list("referral_code", flat=True))

    def unique_code():
        while True:
            code = "".join(secrets.choice(REFERRAL_CODE_ALPHABET) for _ in range(8))
            if code not in existing_codes:
                existing_codes.add(code)
                return code

    for user in User.objects.all():
        paid_count = Event.objects.filter(organizer=user, payment_status="paid").count()
        profile = OrganizerProfile.objects.filter(user=user).first()
        if profile is None:
            OrganizerProfile.objects.create(
                user=user,
                referral_code=unique_code(),
                tier=tier_for_count(paid_count),
            )
        else:
            new_tier = tier_for_count(paid_count)
            if profile.tier != new_tier:
                profile.tier = new_tier
                profile.save(update_fields=["tier"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
        ("events", "0009_accent_event_type_labels"),
    ]

    operations = [
        migrations.RunPython(backfill, noop),
    ]
