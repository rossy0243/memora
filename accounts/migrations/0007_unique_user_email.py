from django.db import migrations

INDEX_NAME = "auth_user_email_lower_uniq"

# Index partiel : unicite sur l'e-mail en minuscules, en ignorant les comptes
# sans e-mail (comptes techniques, superutilisateurs crees sans adresse).
CREATE_INDEX = f"""
CREATE UNIQUE INDEX IF NOT EXISTS {INDEX_NAME}
ON auth_user (LOWER(email))
WHERE email <> '';
"""

DROP_INDEX = f"DROP INDEX IF EXISTS {INDEX_NAME};"


def fail_on_duplicates(apps, schema_editor):
    """Refuse la migration si des doublons existent, avec un message exploitable.

    Sans ce controle, l'index leverait une erreur Postgres brute qui ne dit pas
    QUELS comptes posent probleme. Le blocage est volontaire : fusionner ou
    renommer des comptes est une decision humaine, pas automatisable.
    """
    User = apps.get_model("auth", "User")
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT LOWER(email), COUNT(*)
            FROM auth_user
            WHERE email <> ''
            GROUP BY LOWER(email)
            HAVING COUNT(*) > 1
            """
        )
        duplicates = cursor.fetchall()

    if not duplicates:
        return

    details = []
    for email, count in duplicates:
        usernames = list(
            User.objects.filter(email__iexact=email).values_list("username", flat=True)
        )
        details.append(f"  {email} ({count} comptes : {', '.join(usernames)})")

    raise RuntimeError(
        "Des comptes partagent la meme adresse e-mail ; l'unicite ne peut pas etre "
        "appliquee tant qu'ils existent :\n"
        + "\n".join(details)
        + "\nCorrigez ou supprimez les comptes en double, puis relancez la migration."
    )


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0006_backfill_referred_at"),
    ]

    operations = [
        migrations.RunPython(fail_on_duplicates, migrations.RunPython.noop),
        migrations.RunSQL(CREATE_INDEX, DROP_INDEX),
    ]
