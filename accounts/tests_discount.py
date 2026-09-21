"""Remise de bienvenue : premier evenement avec le code d'un ambassadeur."""
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import CommissionLedger, OrganizerProfile
from core.models import SiteConfiguration
from events.models import Event, EventPlan, EventType
from events.services import send_payment_receipt_email


def make_ambassador(user):
    profile = OrganizerProfile.for_user(user)
    profile.grant_ambassador()
    profile.save(update_fields=["is_ambassador", "became_ambassador_at", "updated_at"])
    return profile


class FirstEventDiscountTests(TestCase):
    def setUp(self):
        cache.clear()
        self.event_type, _ = EventType.objects.get_or_create(
            code="wedding", defaults={"label": "Mariage", "sort_order": 1}
        )
        self.plan = EventPlan.objects.get(code="classique")
        # Fige le prix de la formule a 79 USD : ce test fait tourner beaucoup
        # de calculs sur ce montant precis, independamment du tarif catalogue
        # reellement en vigueur (modifiable en admin a tout moment).
        self.plan.price_amount = 7900
        self.plan.save(update_fields=["price_amount"])
        config = SiteConfiguration.current()
        config.first_event_discount_percent = Decimal("15")
        config.commission_mode = "percent"
        config.commission_referral_percent = Decimal("10")
        config.save()

        self.ambassador = get_user_model().objects.create_user(
            username="ambassadeur", password="secret"
        )
        self.ambassador_profile = make_ambassador(self.ambassador)
        self.newcomer = get_user_model().objects.create_user(
            username="nouveau", password="secret"
        )

    def _refer(self, referrer=None):
        profile = OrganizerProfile.for_user(self.newcomer)
        profile.referred_by = referrer or self.ambassador
        profile.save(update_fields=["referred_by", "updated_at"])
        return profile

    def _event(self, organizer=None, title="Mariage", paid=False):
        return Event.objects.create(
            organizer=organizer or self.newcomer,
            title=title,
            event_type=self.event_type,
            event_date=date(2026, 9, 1),
            plan=self.plan,
            payment_status=Event.PaymentStatus.PAID if paid else Event.PaymentStatus.PENDING,
        )

    def test_referred_newcomer_gets_the_discount_on_the_first_event(self):
        self._refer()
        event = self._event()

        self.assertEqual(event.full_price_amount, 7900)
        self.assertEqual(event.discount_amount, 1185)  # 15 % de 79 USD
        self.assertEqual(event.price_amount, 6715)
        self.assertEqual(event.promo_code, self.ambassador_profile.referral_code)

    def test_organizer_without_referrer_pays_full_price(self):
        event = self._event()

        self.assertEqual(event.price_amount, 7900)
        self.assertFalse(event.has_discount)

    def test_discount_requires_an_ambassador_referrer(self):
        """Un parrain simple organisateur n'ouvre pas droit a la remise."""
        simple = get_user_model().objects.create_user(username="simple", password="secret")
        self._refer(referrer=simple)

        event = self._event()
        self.assertFalse(event.has_discount)
        self.assertEqual(event.price_amount, 7900)

    def test_only_one_pending_event_carries_the_discount(self):
        self._refer()
        first = self._event(title="Premier")
        second = self._event(title="Second")

        self.assertTrue(first.has_discount)
        self.assertFalse(second.has_discount)
        self.assertEqual(second.price_amount, 7900)

    def test_discount_is_consumed_at_payment_not_at_creation(self):
        self._refer()
        event = self._event()
        profile = OrganizerProfile.for_user(self.newcomer)
        self.assertIsNone(profile.first_event_discount_used_at)

        event.payment_status = Event.PaymentStatus.PAID
        event.save()

        profile.refresh_from_db()
        self.assertIsNotNone(profile.first_event_discount_used_at)

    def test_second_event_after_payment_is_full_price(self):
        self._refer()
        first = self._event(title="Premier")
        first.payment_status = Event.PaymentStatus.PAID
        first.save()

        second = self._event(title="Second")
        self.assertFalse(second.has_discount)
        self.assertEqual(second.price_amount, 7900)

    def test_referral_commission_is_computed_on_the_discounted_price(self):
        """Decision produit : on ne verse pas de commission sur de l'argent non encaisse."""
        self._refer()
        event = self._event()
        event.payment_status = Event.PaymentStatus.PAID
        event.save()

        entry = CommissionLedger.objects.get(
            event=event, kind=CommissionLedger.Kind.REFERRAL_EVENT
        )
        self.assertEqual(entry.beneficiary, self.ambassador)
        # 10 % de 67,15 USD (arrondi commercial), et non 10 % de 79 USD.
        self.assertEqual(entry.amount, 672)
        self.assertEqual(event.price_amount, 6715)


    def test_the_discount_survives_later_saves_of_the_paid_event(self):
        """Regression : chaque enregistrement d'un evenement paye relance le calcul des
        commissions. Le 2e enregistrement (envoi du recu, reglage admin...) prenait la remise
        deja consommee pour celle d'un AUTRE evenement et remettait le prix plein."""
        self._refer()
        event = self._event()
        event.payment_status = Event.PaymentStatus.PAID
        event.save()

        event.save()  # meme instance, enregistrement suivant
        Event.objects.get(pk=event.pk).save()  # instance rechargee (autre requete)
        event.receipt_sent_at = timezone.now()
        event.save(update_fields=["receipt_sent_at", "updated_at"])  # envoi du recu

        event.refresh_from_db()
        self.assertEqual(event.discount_amount, 1185)
        self.assertEqual(event.price_amount, 6715)
        self.assertEqual(CommissionLedger.objects.filter(event=event).count(), 1)

    def test_receipt_email_after_payment_keeps_the_discounted_price(self):
        self.newcomer.email = "nouveau@example.com"  # sans e-mail, aucun recu n'est envoye
        self.newcomer.save(update_fields=["email"])
        self._refer()
        event = self._event()
        event.payment_status = Event.PaymentStatus.PAID
        event.save()

        send_payment_receipt_email(event)

        event.refresh_from_db()
        self.assertIsNotNone(event.receipt_sent_at)
        self.assertEqual(event.price_amount, 6715)
        self.assertEqual(event.discount_amount, 1185)

    def test_saving_again_after_a_race_keeps_each_event_at_its_own_price(self):
        self._refer()
        first = self._event(title="Course E")
        second = self._event(title="Course F")
        Event.objects.filter(pk=second.pk).update(
            discount_amount=first.discount_amount,
            discount_percent=first.discount_percent,
            price_amount=first.price_amount,
        )
        second.refresh_from_db()
        first.payment_status = Event.PaymentStatus.PAID
        first.save()
        second.payment_status = Event.PaymentStatus.PAID
        second.save()

        Event.objects.get(pk=first.pk).save()
        Event.objects.get(pk=second.pk).save()

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual((first.price_amount, first.discount_amount), (6715, 1185))
        self.assertEqual((second.price_amount, second.discount_amount), (7900, 0))

    def test_a_race_cannot_grant_two_discounts(self):
        """Deux creations simultanees ne doivent pas donner deux remises.

        On simule l'issue de la course : deux evenements portent la remise. Le
        paiement doit ramener le second au plein tarif.
        """
        self._refer()
        first = self._event(title="Course A")
        second = self._event(title="Course B")
        # Etat qu'aurait produit un controle d'eligibilite double.
        Event.objects.filter(pk=second.pk).update(
            discount_amount=first.discount_amount,
            discount_percent=first.discount_percent,
            price_amount=first.price_amount,
        )
        second.refresh_from_db()
        self.assertEqual(second.price_amount, 6715)

        first.payment_status = Event.PaymentStatus.PAID
        first.save()
        second.payment_status = Event.PaymentStatus.PAID
        second.save()

        second.refresh_from_db()
        self.assertEqual(second.price_amount, 7900)
        self.assertEqual(second.discount_amount, 0)
        # Le premier garde bien sa remise.
        first.refresh_from_db()
        self.assertEqual(first.price_amount, 6715)

    def test_reverted_discount_does_not_shrink_the_commission(self):
        """La commission du parrain suit le prix retabli, pas le prix remise."""
        self._refer()
        first = self._event(title="Course C")
        second = self._event(title="Course D")
        Event.objects.filter(pk=second.pk).update(
            discount_amount=first.discount_amount,
            discount_percent=first.discount_percent,
            price_amount=first.price_amount,
        )
        second.refresh_from_db()

        first.payment_status = Event.PaymentStatus.PAID
        first.save()
        second.payment_status = Event.PaymentStatus.PAID
        second.save()

        entry = CommissionLedger.objects.get(
            event=second, kind=CommissionLedger.Kind.REFERRAL_EVENT
        )
        self.assertEqual(entry.amount, 790)  # 10 % de 79 USD, plein tarif

    def test_discount_can_be_disabled_from_admin(self):
        config = SiteConfiguration.current()
        config.first_event_discount_percent = Decimal("0")
        config.save()

        self._refer()
        event = self._event()
        self.assertFalse(event.has_discount)
        self.assertEqual(event.price_amount, 7900)


class PromoCodeFormTests(TestCase):
    def setUp(self):
        cache.clear()
        self.event_type, _ = EventType.objects.get_or_create(
            code="wedding", defaults={"label": "Mariage", "sort_order": 1}
        )
        self.plan = EventPlan.objects.get(code="classique")
        # Meme raison qu'au-dessus : fige a 79 USD pour des calculs stables.
        self.plan.price_amount = 7900
        self.plan.save(update_fields=["price_amount"])
        config = SiteConfiguration.current()
        config.first_event_discount_percent = Decimal("15")
        config.save()

        self.ambassador = get_user_model().objects.create_user(
            username="ambassadeur2", password="secret"
        )
        self.ambassador_profile = make_ambassador(self.ambassador)
        self.newcomer = get_user_model().objects.create_user(
            username="nouveau2", password="secret", email="n@memora.test"
        )

    def _post(self, promo_code):
        self.client.force_login(self.newcomer)
        return self.client.post(
            reverse("events:create"),
            {
                "title": "Mariage code promo",
                "couple_name": "",
                "event_type": self.event_type.pk,
                "custom_event_type_label": "",
                "plan": self.plan.pk,
                "promo_code": promo_code,
                "event_date": "2026-09-12",
                "welcome_message": "",
                "guest_access_code": "",
            },
        )

    def test_code_entered_at_creation_grants_the_discount_and_links_the_referrer(self):
        response = self._post(self.ambassador_profile.referral_code)
        self.assertEqual(response.status_code, 302)

        event = Event.objects.get(title="Mariage code promo")
        self.assertTrue(event.has_discount)
        self.assertEqual(event.price_amount, 6715)
        # L'ambassadeur devient le parrain : il touchera aussi les commissions suivantes.
        self.assertEqual(
            OrganizerProfile.for_user(self.newcomer).referred_by, self.ambassador
        )

    def test_unknown_code_is_rejected(self):
        response = self._post("INCONNU12")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ce code est inconnu.")
        self.assertFalse(Event.objects.filter(title="Mariage code promo").exists())

    def test_non_ambassador_code_is_rejected(self):
        simple = get_user_model().objects.create_user(username="simple2", password="secret")
        code = OrganizerProfile.for_user(simple).referral_code

        response = self._post(code)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "code ambassadeur")

    def test_own_code_is_rejected(self):
        own_code = OrganizerProfile.for_user(self.newcomer).referral_code

        response = self._post(own_code)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "votre propre code")

    def test_existing_referrer_is_never_reassigned(self):
        """Un filleul ne change pas d'ambassadeur en saisissant un autre code."""
        first_ambassador = get_user_model().objects.create_user(
            username="ambassadeur3", password="secret"
        )
        make_ambassador(first_ambassador)
        profile = OrganizerProfile.for_user(self.newcomer)
        profile.referred_by = first_ambassador
        profile.save(update_fields=["referred_by", "updated_at"])

        self._post(self.ambassador_profile.referral_code)

        profile.refresh_from_db()
        self.assertEqual(profile.referred_by, first_ambassador)

    def test_promo_field_is_prefilled_for_a_referred_organizer(self):
        profile = OrganizerProfile.for_user(self.newcomer)
        profile.referred_by = self.ambassador
        profile.save(update_fields=["referred_by", "updated_at"])

        self.client.force_login(self.newcomer)
        response = self.client.get(reverse("events:create"))

        self.assertContains(response, self.ambassador_profile.referral_code)


class AuditWelcomeDiscountsCommandTests(TestCase):
    """L'audit repere un evenement dont la remise a ete annulee, et laisse les autres tranquilles."""

    def setUp(self):
        cache.clear()
        self.event_type, _ = EventType.objects.get_or_create(
            code="wedding", defaults={"label": "Mariage", "sort_order": 1}
        )
        self.ambassador = get_user_model().objects.create_user(username="amb-audit", password="secret")
        make_ambassador(self.ambassador)
        self.newcomer = get_user_model().objects.create_user(username="nouveau-audit", password="secret")
        profile = OrganizerProfile.for_user(self.newcomer)
        profile.referred_by = self.ambassador
        profile.save(update_fields=["referred_by", "updated_at"])

    def _run(self):
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("audit_welcome_discounts", stdout=out)
        return out.getvalue()

    def _paid_discounted_event(self):
        event = Event.objects.create(
            organizer=self.newcomer, title="Audit", event_type=self.event_type, event_date=date(2026, 9, 1),
            plan=EventPlan.objects.get(code="classique"),
        )
        event.payment_status = Event.PaymentStatus.PAID
        event.save()
        return event

    def test_a_healthy_discounted_event_is_not_flagged(self):
        self._paid_discounted_event()

        self.assertIn("Aucun evenement touche.", self._run())

    def test_an_event_whose_discount_was_wiped_is_flagged(self):
        event = self._paid_discounted_event()
        # Etat laisse par l'ancien defaut : prix plein, remise a zero, code conserve.
        Event.objects.filter(pk=event.pk).update(price_amount=event.full_price_amount, discount_amount=0, discount_percent=0)

        report = self._run()

        self.assertIn("1 suspect(s)", report)
        self.assertIn(f"evenement {event.pk}", report)
