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

        # Commission sur l'événement propre : montant selon le palier atteint, figé.
        tier = configuration.tier_for_paid_count(paid_count)
        own_amount = configuration.commission_amount_for_paid_count(paid_count)
        if own_amount:
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

        # Commission de parrainage : versée au parrain pour chaque événement payé du filleul.
        referrer = organizer_profile.referred_by
        if referrer and configuration.commission_referral_amount:
            entry, was_created = CommissionLedger.objects.get_or_create(
                event=event,
                kind=CommissionLedger.Kind.REFERRAL_EVENT,
                defaults={
                    "beneficiary": referrer,
                    "amount": configuration.commission_referral_amount,
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

    current_amount = configuration.commission_amount_for_paid_count(max(paid_count, 1))

    return {
        "tier": tier,
        "tier_label": profile.Tier(tier).label,
        "paid_count": paid_count,
        "current_rate": format_price_amount(current_amount, currency),
        "next_tier_label": next_label,
        "events_to_next_tier": remaining,
    }
