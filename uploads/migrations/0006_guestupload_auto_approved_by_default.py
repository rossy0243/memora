from django.db import migrations, models


def approve_pending_uploads(apps, schema_editor):
    GuestUpload = apps.get_model("uploads", "GuestUpload")
    GuestUpload.objects.filter(moderation_status="pending").update(moderation_status="approved")


def restore_pending_uploads(apps, schema_editor):
    GuestUpload = apps.get_model("uploads", "GuestUpload")
    GuestUpload.objects.filter(moderation_status="approved").update(moderation_status="pending")


class Migration(migrations.Migration):

    dependencies = [
        ("uploads", "0005_guestupload_moderation_status"),
    ]

    operations = [
        migrations.RunPython(approve_pending_uploads, restore_pending_uploads),
        migrations.AlterField(
            model_name="guestupload",
            name="moderation_status",
            field=models.CharField(
                choices=[
                    ("pending", "A verifier"),
                    ("approved", "Accepte"),
                    ("rejected", "Rejete"),
                ],
                default="approved",
                max_length=16,
            ),
        ),
    ]
