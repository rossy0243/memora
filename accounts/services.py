from django.db import transaction

from core.models import SiteConfiguration, format_price_amount

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

        # Commission de parrainage : le parrain doit être ambassadeur ET l'affiliation
        # doit courir encore (elle expire après la durée réglée en admin).
        referrer = organizer_profile.referred_by
        referrer_is_ambassador = bool(
            referrer
            and organizer_profile.referral_is_active
            and OrganizerProfile.for_user(referrer).is_ambassador
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
    available = 0  # en attente ET pas deja engage dans une demande de retrait
    currency = SiteConfiguration.current().event_price_currency
    for entry in entries:
        currency = entry.currency or currency
        if entry.status == CommissionLedger.Status.PAID:
            paid += entry.amount
        else:
            pending += entry.amount
            if entry.payout_request_id is None:
                available += entry.amount
    return {
        "entries": entries,
        "pending_amount": pending,
        "paid_amount": paid,
        "available_amount": available,
        "total_amount": pending + paid,
        "currency": currency,
    }


def monthly_earnings_for_user(user, months=6):
    """Gains par mois, du plus ancien au plus recent — l'evolution du dashboard.

    Renvoie une liste de dicts prets a afficher, avec une hauteur relative pour
    dessiner les barres sans bibliotheque de graphiques.
    """
    from django.db.models import Sum
    from django.db.models.functions import TruncMonth

    rows = (
        CommissionLedger.objects.filter(beneficiary=user)
        .annotate(month=TruncMonth("created_at"))
        .values("month")
        .annotate(total=Sum("amount"))
        .order_by("-month")[:months]
    )
    rows = list(reversed(rows))
    if not rows:
        return []

    currency = SiteConfiguration.current().event_price_currency
    peak = max(row["total"] for row in rows) or 1
    labels = [
        "janv.", "févr.", "mars", "avril", "mai", "juin",
        "juil.", "août", "sept.", "oct.", "nov.", "déc.",
    ]
    return [
        {
            "label": f"{labels[row['month'].month - 1]} {row['month'].strftime('%y')}",
            "amount": row["total"],
            "formatted": format_price_amount(row["total"], currency),
            "height_percent": max(int(row["total"] * 100 / peak), 4),
        }
        for row in rows
    ]


def request_payout(user, method, payout_details):
    """Cree une demande de retrait portant tous les gains disponibles.

    Leve ValueError si le solde est sous le minimum ou si une demande est deja
    ouverte : deux demandes concurrentes engageraient deux fois le meme argent.
    """
    from .models import PayoutRequest

    configuration = SiteConfiguration.current()
    summary = commission_summary_for_user(user)
    available = summary["available_amount"]

    if PayoutRequest.objects.filter(
        beneficiary=user,
        status__in=[PayoutRequest.Status.PENDING, PayoutRequest.Status.APPROVED],
    ).exists():
        raise ValueError("Vous avez déjà une demande de retrait en cours.")

    minimum = configuration.minimum_payout_amount
    if available < minimum:
        raise ValueError(
            f"Le montant minimum pour un retrait est de {configuration.formatted_minimum_payout}."
        )

    with transaction.atomic():
        payout = PayoutRequest.objects.create(
            beneficiary=user,
            amount=available,
            currency=summary["currency"],
            method=method,
            payout_details=payout_details,
        )
        # On engage les commissions disponibles : elles ne peuvent plus etre
        # incluses dans une autre demande.
        CommissionLedger.objects.filter(
            beneficiary=user,
            status=CommissionLedger.Status.PENDING,
            payout_request__isnull=True,
        ).update(payout_request=payout)
    return payout


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
