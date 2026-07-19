from django.db import migrations


LABEL_FIXES = {
    "ceremony": ("Ceremonie", "Cérémonie"),
    "arrival": ("Arrivee", "Arrivée"),
    "reception": ("Reception", "Réception"),
    "cake": ("Gateau", "Gâteau"),
    "funny": ("Moment drole", "Moment drôle"),
    "emotional": ("Moment emouvant", "Moment émouvant"),
}

MODEL_NAMES = ("UploadCategory", "UploadCategoryTemplate", "MomentTemplate")


def accent_labels(apps, schema_editor):
    for model_name in MODEL_NAMES:
        model = apps.get_model("uploads", model_name)
        for code, (old_label, new_label) in LABEL_FIXES.items():
            model.objects.filter(code=code, label=old_label).update(label=new_label)


def unaccent_labels(apps, schema_editor):
    for model_name in MODEL_NAMES:
        model = apps.get_model("uploads", model_name)
        for code, (old_label, new_label) in LABEL_FIXES.items():
            model.objects.filter(code=code, label=new_label).update(label=old_label)


class Migration(migrations.Migration):

    dependencies = [
        ("uploads", "0007_momenttemplate"),
    ]

    operations = [
        migrations.RunPython(accent_labels, unaccent_labels),
    ]
