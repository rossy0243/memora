from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("uploads", "0004_uploadcategorytemplate"),
    ]

    operations = [
        migrations.AddField(
            model_name="guestupload",
            name="moderation_status",
            field=models.CharField(
                choices=[
                    ("pending", "En attente"),
                    ("approved", "Approuve"),
                    ("rejected", "Rejete"),
                ],
                default="approved",
                max_length=16,
            ),
            preserve_default=False,
        ),
        migrations.AddIndex(
            model_name="guestupload",
            index=models.Index(fields=["event", "moderation_status"], name="uploads_gue_event_i_adc900_idx"),
        ),
        migrations.AlterField(
            model_name="guestupload",
            name="moderation_status",
            field=models.CharField(
                choices=[
                    ("pending", "En attente"),
                    ("approved", "Approuve"),
                    ("rejected", "Rejete"),
                ],
                default="pending",
                max_length=16,
            ),
        ),
    ]
