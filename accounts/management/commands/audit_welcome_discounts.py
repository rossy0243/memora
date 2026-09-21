"""Audit (lecture seule) : evenements dont la remise de bienvenue a pu etre annulee par erreur.

    python manage.py audit_welcome_discounts

Avant le correctif de accounts.services.record_event_commissions, un 2e enregistrement d'un
evenement remise et paye (envoi du recu, reglage admin...) remettait le prix plein alors que
la remise etait bien consommee et la commission calculee sur le prix remise.

Signature d'un evenement touche : paye, code ambassadeur conserve (`promo_code`), remise a 0,
PREMIER evenement paye de l'organisateur, et remise de bienvenue marquee consommee.
Ne modifie rien.
"""
from django.core.management.base import BaseCommand

from accounts.models import CommissionLedger, OrganizerProfile
from events.models import Event


class Command(BaseCommand):
    help = "Liste les evenements dont la remise de bienvenue a pu etre annulee par erreur (lecture seule)."

    def handle(self, *args, **options):
        suspects = []
        paid = Event.objects.filter(payment_status=Event.PaymentStatus.PAID).exclude(promo_code="")
        for event in paid.select_related("organizer").order_by("paid_at"):
            if event.discount_amount:
                continue
            profile = OrganizerProfile.objects.filter(user=event.organizer).first()
            if not profile or not profile.first_event_discount_used_at:
                continue
            first_paid = (
                Event.objects.filter(organizer=event.organizer, payment_status=Event.PaymentStatus.PAID)
                .order_by("paid_at", "pk")
                .first()
            )
            if first_paid is None or first_paid.pk != event.pk:
                continue  # 2e evenement remise a la suite d'une course : plein tarif normal
            suspects.append(event)

        self.stdout.write(f"{paid.count()} evenement(s) paye(s) avec un code ambassadeur, {len(suspects)} suspect(s).")
        for event in suspects:
            commission = CommissionLedger.objects.filter(event=event, kind=CommissionLedger.Kind.REFERRAL_EVENT).first()
            self.stdout.write(
                f"  evenement {event.pk} « {event.title} » organisateur={event.organizer.username} "
                f"code={event.promo_code} prix affiche={event.price_amount / 100:.2f} {event.price_currency} "
                f"(plein tarif {event.full_price_amount / 100:.2f}) "
                f"commission parrain={'%.2f' % (commission.amount / 100) if commission else '-'}"
            )
        if not suspects:
            self.stdout.write("Aucun evenement touche.")
