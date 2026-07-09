import django.db.models.deletion
from django.db import migrations, models


CATEGORY_TEMPLATES = {
    "wedding": [
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
    ],
    "birthday": [
        ("arrival", "Arrivee des invites", 1),
        ("aperitif", "Aperitif", 2),
        ("meal", "Repas", 3),
        ("speech", "Discours", 4),
        ("cake", "Gateau", 5),
        ("gifts", "Cadeaux", 6),
        ("dancefloor", "Piste de danse", 7),
        ("funny", "Moment drole", 8),
        ("other", "Autre", 9),
    ],
    "corporate": [
        ("welcome", "Accueil", 1),
        ("keynote", "Conference", 2),
        ("workshop", "Atelier", 3),
        ("networking", "Networking", 4),
        ("cocktail", "Cocktail", 5),
        ("team", "Equipe", 6),
        ("funny", "Moment spontane", 7),
        ("other", "Autre", 8),
    ],
    "other": [
        ("arrival", "Arrivee", 1),
        ("highlight", "Temps fort", 2),
        ("speech", "Discours", 3),
        ("group", "Photo de groupe", 4),
        ("funny", "Moment drole", 5),
        ("emotional", "Moment emouvant", 6),
        ("other", "Autre", 7),
    ],
}


def create_category_templates(apps, schema_editor):
    EventType = apps.get_model("events", "EventType")
    UploadCategoryTemplate = apps.get_model("uploads", "UploadCategoryTemplate")

    for event_type_code, categories in CATEGORY_TEMPLATES.items():
        event_type = EventType.objects.filter(code=event_type_code).first()
        if event_type is None:
            continue
        for code, label, sort_order in categories:
            UploadCategoryTemplate.objects.update_or_create(
                event_type=event_type,
                code=code,
                defaults={
                    "label": label,
                    "sort_order": sort_order,
                    "is_active": True,
                },
            )


def remove_category_templates(apps, schema_editor):
    EventType = apps.get_model("events", "EventType")
    UploadCategoryTemplate = apps.get_model("uploads", "UploadCategoryTemplate")

    for event_type_code, categories in CATEGORY_TEMPLATES.items():
        event_type = EventType.objects.filter(code=event_type_code).first()
        if event_type is None:
            continue
        UploadCategoryTemplate.objects.filter(
            event_type=event_type,
            code__in=[code for code, _, _ in categories],
        ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("events", "0002_event_type_model"),
        ("uploads", "0003_categories_per_event"),
    ]

    operations = [
        migrations.CreateModel(
            name="UploadCategoryTemplate",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.SlugField(max_length=40)),
                ("label", models.CharField(max_length=80)),
                ("sort_order", models.PositiveSmallIntegerField(default=0)),
                ("is_active", models.BooleanField(default=True)),
                (
                    "event_type",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="upload_category_templates",
                        to="events.eventtype",
                    ),
                ),
            ],
            options={
                "ordering": ["event_type_id", "sort_order", "label"],
                "verbose_name": "modele de moment",
                "verbose_name_plural": "modeles de moments",
            },
        ),
        migrations.AddConstraint(
            model_name="uploadcategorytemplate",
            constraint=models.UniqueConstraint(
                fields=("event_type", "code"),
                name="unique_upload_category_template_per_event_type",
            ),
        ),
        migrations.RunPython(create_category_templates, remove_category_templates),
    ]
