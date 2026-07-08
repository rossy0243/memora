from django.db import migrations


CATEGORIES = [
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


def create_categories(apps, schema_editor):
    UploadCategory = apps.get_model("uploads", "UploadCategory")
    for code, label, sort_order in CATEGORIES:
        UploadCategory.objects.update_or_create(
            code=code,
            defaults={
                "label": label,
                "sort_order": sort_order,
                "is_active": True,
            },
        )


def remove_categories(apps, schema_editor):
    UploadCategory = apps.get_model("uploads", "UploadCategory")
    UploadCategory.objects.filter(code__in=[code for code, _, _ in CATEGORIES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("uploads", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(create_categories, remove_categories),
    ]
