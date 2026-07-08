import django.db.models.deletion
from django.db import migrations, models


DEFAULT_CATEGORIES = [
    ("ceremony", "Ceremonie", 1),
    ("arrival", "Arrivee", 2),
    ("cocktail", "Cocktail", 3),
    ("reception", "Reception", 4),
    ("speech", "Discours", 5),
    ("dancefloor", "Piste de danse", 6),
    ("cake", "Gateau", 7),
    ("funny", "Moment drole", 8),
    ("emotional", "Moment emouvant", 9),
    ("other", "Autre", 10),
]


def move_categories_to_events(apps, schema_editor):
    Event = apps.get_model("events", "Event")
    UploadCategory = apps.get_model("uploads", "UploadCategory")
    GuestUpload = apps.get_model("uploads", "GuestUpload")

    global_categories = list(UploadCategory.objects.filter(event__isnull=True).order_by("sort_order", "label"))
    defaults = global_categories or [
        type("CategorySeed", (), {"code": code, "label": label, "sort_order": sort_order, "is_active": True})
        for code, label, sort_order in DEFAULT_CATEGORIES
    ]

    for event in Event.objects.all():
        for category in defaults:
            event_category, _ = UploadCategory.objects.get_or_create(
                event=event,
                code=category.code,
                defaults={
                    "label": category.label,
                    "sort_order": category.sort_order,
                    "is_active": category.is_active,
                },
            )
            GuestUpload.objects.filter(
                event=event,
                category__event__isnull=True,
                category__code=category.code,
            ).update(category=event_category)

    UploadCategory.objects.filter(event__isnull=True).delete()


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("events", "0001_initial"),
        ("uploads", "0002_seed_upload_categories"),
    ]

    operations = [
        migrations.AddField(
            model_name="uploadcategory",
            name="event",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="upload_categories",
                to="events.event",
            ),
        ),
        migrations.AlterField(
            model_name="uploadcategory",
            name="code",
            field=models.SlugField(max_length=40),
        ),
        migrations.RunPython(move_categories_to_events, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="uploadcategory",
            name="event",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="upload_categories",
                to="events.event",
            ),
        ),
        migrations.AddConstraint(
            model_name="uploadcategory",
            constraint=models.UniqueConstraint(fields=("event", "code"), name="unique_upload_category_per_event"),
        ),
        migrations.AlterModelOptions(
            name="uploadcategory",
            options={
                "ordering": ["event_id", "sort_order", "label"],
                "verbose_name": "categorie d'upload",
                "verbose_name_plural": "categories d'upload",
            },
        ),
    ]
