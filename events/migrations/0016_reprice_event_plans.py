from django.db import migrations

# Repositionnement des formules : le nombre d'invites devient l'element le
# plus visible (labels et gabarits cote templates), et les prix sont revus a
# la hausse pour refleter le cout reel du rendu premium Remotion (Pro Plus),
# adopte apres la premiere grille — celle-ci supposait un cout variable
# negligeable (voir 0011_default_event_plans), ce qui n'est plus le cas :
# plus l'evenement est grand, plus le montage du livre d'or (integral) et le
# volume de medias a traiter allongent le temps de rendu factures a
# l'execution. La hausse est donc plus marquee sur les formules hautes.
# Modifiable a tout moment depuis l'admin Django (EventPlan.price_amount).
NEW_PRICES = {
    "intime": 5900,       # 49 -> 59 USD
    "classique": 8900,    # 79 -> 89 USD
    "grand-jour": 14900,  # 129 -> 149 USD
    "prestige": 24900,    # 199 -> 249 USD
}
OLD_PRICES = {
    "intime": 4900,
    "classique": 7900,
    "grand-jour": 12900,
    "prestige": 19900,
}


def apply_new_prices(apps, schema_editor):
    EventPlan = apps.get_model("events", "EventPlan")
    for code, price_amount in NEW_PRICES.items():
        EventPlan.objects.filter(code=code).update(price_amount=price_amount)


def restore_old_prices(apps, schema_editor):
    EventPlan = apps.get_model("events", "EventPlan")
    for code, price_amount in OLD_PRICES.items():
        EventPlan.objects.filter(code=code).update(price_amount=price_amount)


class Migration(migrations.Migration):

    dependencies = [
        ("events", "0015_remove_event_guestbook_agent_and_more"),
    ]

    operations = [
        migrations.RunPython(apply_new_prices, restore_old_prices),
    ]
