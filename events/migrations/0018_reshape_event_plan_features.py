from django.db import migrations

# Repositionnement des offres (2026-09) : Intime et Classique restent
# l'essentiel (film + teaser + camera) ; Grand jour ajoute le livre d'or video
# avec un agent Memora et devient la formule vedette ; Prestige passe sur
# devis avec plusieurs agents Memora, et sort du parcours de creation en
# libre-service (voir EventForm). Modifiable a tout moment depuis l'admin.
PLAN_UPDATES = {
    "intime": {
        "includes_guestbook": False,
        "guestbook_agents_included": 0,
        "requires_quote": False,
        "is_default": False,
    },
    "classique": {
        "includes_guestbook": False,
        "guestbook_agents_included": 0,
        "requires_quote": False,
        "is_default": False,
        # Ce tagline promettait d'etre "la formule la plus choisie" : ce role
        # revient maintenant a Grand jour.
        "tagline": "L'essentiel, à tarif maîtrisé.",
    },
    "grand-jour": {
        "includes_guestbook": True,
        "guestbook_agents_included": 1,
        "requires_quote": False,
        "is_default": True,
        "tagline": "La formule la plus choisie, avec le livre d'or vidéo.",
    },
    "prestige": {
        "includes_guestbook": True,
        "guestbook_agents_included": 3,
        "requires_quote": True,
        "is_default": False,
        "tagline": "Sur mesure, pour les événements d'exception.",
    },
}

PREVIOUS_STATE = {
    "intime": {
        "includes_guestbook": False,
        "guestbook_agents_included": 0,
        "requires_quote": False,
        "is_default": False,
        "tagline": "Les petits comités, en toute simplicité.",
    },
    "classique": {
        "includes_guestbook": False,
        "guestbook_agents_included": 0,
        "requires_quote": False,
        "is_default": True,
        "tagline": "La formule la plus choisie.",
    },
    "grand-jour": {
        "includes_guestbook": False,
        "guestbook_agents_included": 0,
        "requires_quote": False,
        "is_default": False,
        "tagline": "Pour les grandes réceptions.",
    },
    "prestige": {
        "includes_guestbook": False,
        "guestbook_agents_included": 0,
        "requires_quote": False,
        "is_default": False,
        "tagline": "Sans compter, pour les événements d'exception.",
    },
}


def _apply(apps, updates):
    EventPlan = apps.get_model("events", "EventPlan")
    for code, fields in updates.items():
        EventPlan.objects.filter(code=code).update(**fields)


def reshape_forward(apps, schema_editor):
    _apply(apps, PLAN_UPDATES)


def reshape_backward(apps, schema_editor):
    _apply(apps, PREVIOUS_STATE)


class Migration(migrations.Migration):

    dependencies = [
        ("events", "0017_eventplan_guestbook_agents_included_and_more"),
    ]

    operations = [
        migrations.RunPython(reshape_forward, reshape_backward),
    ]
