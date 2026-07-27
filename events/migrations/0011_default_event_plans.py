from django.db import migrations

# Formules de depart, alignees sur l'analyse de couts (infra ~40 USD/mois fixe,
# variable negligeable) : le prix suit le BUDGET de l'evenement, pas son cout.
# Le quota de souvenirs est ce qui est reellement applique ; le nombre d'invites
# est l'etiquette commerciale. Tout est modifiable en admin.
DEFAULT_PLANS = [
    {
        "code": "intime",
        "label": "Intime",
        "tagline": "Les petits comités, en toute simplicité.",
        "max_guests": 50,
        "upload_quota": 300,
        "price_amount": 4900,
        "sort_order": 10,
        "is_default": False,
    },
    {
        "code": "classique",
        "label": "Classique",
        "tagline": "La formule la plus choisie.",
        "max_guests": 150,
        "upload_quota": 800,
        "price_amount": 7900,
        "sort_order": 20,
        "is_default": True,
    },
    {
        "code": "grand-jour",
        "label": "Grand jour",
        "tagline": "Pour les grandes réceptions.",
        "max_guests": 300,
        "upload_quota": 1500,
        "price_amount": 12900,
        "sort_order": 30,
        "is_default": False,
    },
    {
        "code": "prestige",
        "label": "Prestige",
        "tagline": "Sans compter, pour les événements d'exception.",
        "max_guests": 0,
        "upload_quota": 3000,
        "price_amount": 19900,
        "sort_order": 40,
        "is_default": False,
    },
]


def create_default_plans(apps, schema_editor):
    EventPlan = apps.get_model("events", "EventPlan")
    for plan in DEFAULT_PLANS:
        EventPlan.objects.update_or_create(code=plan["code"], defaults=plan)


def remove_default_plans(apps, schema_editor):
    EventPlan = apps.get_model("events", "EventPlan")
    codes = [plan["code"] for plan in DEFAULT_PLANS]
    # On ne supprime que les formules encore rattachees a aucun evenement.
    EventPlan.objects.filter(code__in=codes, events__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("events", "0010_eventplan_event_plan"),
    ]

    operations = [
        migrations.RunPython(create_default_plans, remove_default_plans),
    ]
