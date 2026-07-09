from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("events", "0005_reset_qr_codes_for_private_links"),
    ]

    operations = [
        migrations.AddField(
            model_name="event",
            name="guest_access_code",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Code optionnel a donner uniquement aux invites presents.",
                max_length=24,
            ),
            preserve_default=False,
        ),
    ]
