from django.db import transaction

from core.models import SiteConfiguration

from .models import CommissionLedger, OrganizerProfile


def record_event_commissions(event):
    """Crée les commissions liées à un événement payé et met à jour le palier. Idempotent."""
    if not event.pk or not event.is_paid:
        return []

    configuration = SiteConfiguration.current()
    created = []

    with transaction.atomic():
        organizer_profile = OrganizerProfile.for_user(event.organizer)
        paid_count = organizer_profile.paid_events_count()

        # La remise de bienvenue est consommee au paiement, pas a la creation :
        # un evenement cree puis abandonne ne doit pas la bruler.
        if event.discount_amount:
            organizer_profile.consume_first_event_discount()

        # Commission sur l'événement propre : réservée aux ambassadeurs désignés par Memora.
        tier = configuration.tier_for_paid_count(paid_count)
        # En mode pourcentage, la commission suit le prix reel de l'evenement
        # (donc sa formule) : un evenement Prestige rapporte plus qu'un Intime.
        own_amount = configuration.commission_amount_for_paid_count(
            paid_count, price_amount=event.price_amount
        )
        if organizer_profile.is_ambassador and own_amount:
            entry, was_created = CommissionLedger.objects.get_or_create(
                event=event,
                kind=CommissionLedger.Kind.OWN_EVENT,
                defaults={
                    "beneficiary": event.organizer,
                    "tier": tier,
                    "amount": own_amount,
                    "currency": configuration.event_price_currency,
                },
            )
            if was_created:
                created.append(entry)

        # Le palier de l'organisateur suit son nombre d'événements payés.
        organizer_profile.refresh_tier(paid_count=paid_count)

        # Commission de parrainage : le parrain doit lui aussi être ambassadeur.
        referrer = organizer_profile.referred_by
        referrer_is_ambassador = bool(
            referrer and OrganizerProfile.for_user(referrer).is_ambassador
        )
        referral_amount = configuration.referral_commission_amount(
            price_amount=event.price_amount
        )
        if referrer_is_ambassador and referral_amount:
            entry, was_created = CommissionLedger.objects.get_or_create(
                event=event,
                kind=CommissionLedger.Kind.REFERRAL_EVENT,
                defaults={
                    "beneficiary": referrer,
                    "amount": referral_amount,
                    "currency": configuration.event_price_currency,
                },
            )
            if was_created:
                created.append(entry)

    return created


def commission_summary_for_user(user):
    entries = CommissionLedger.objects.filter(beneficiary=user)
    pending = 0
    paid = 0
    currency = SiteConfiguration.current().event_price_currency
    for entry in entries:
        currency = entry.currency or currency
        if entry.status == CommissionLedger.Status.PAID:
            paid += entry.amount
        else:
            pending += entry.amount
    return {
        "entries": entries,
        "pending_amount": pending,
        "paid_amount": paid,
        "total_amount": pending + paid,
        "currency": currency,
    }


def tier_progress_for_profile(profile):
    """Infos de palier pour le dashboard : palier courant, taux, progression vers le suivant."""
    configuration = SiteConfiguration.current()
    paid_count = profile.paid_events_count()
    tier = configuration.tier_for_paid_count(max(paid_count, 1))
    currency = configuration.event_price_currency

    from core.models import format_price_amount

    if tier == "premium":
        next_label = None
        remaining = 0
    elif tier == "medium":
        next_label = "Premium"
        remaining = max(configuration.tier_premium_min_events - paid_count, 0)
    else:
        next_label = "Medium"
        remaining = max(configuration.tier_medium_min_events - paid_count, 0)

    # En mode pourcentage on affiche le taux (« 15 % »), pas un montant : celui-ci
    # depend de la formule de chaque evenement.
    if configuration.uses_percent_commissions:
        percent = configuration.commission_percent_for_paid_count(max(paid_count, 1))
        current_rate = f"{percent.normalize():f} %"
    else:
        current_amount = configuration.commission_amount_for_paid_count(max(paid_count, 1))
        current_rate = format_price_amount(current_amount, currency)

    return {
        "tier": tier,
        "tier_label": profile.Tier(tier).label,
        "paid_count": paid_count,
        "current_rate": current_rate,
        "next_tier_label": next_label,
        "events_to_next_tier": remaining,
    }
