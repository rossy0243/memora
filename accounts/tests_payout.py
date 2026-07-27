"""Affiliation a duree limitee, evolution des gains et demandes de retrait."""
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import CommissionLedger, OrganizerProfile, PayoutRequest
from accounts.services import (
    commission_summary_for_user,
    monthly_earnings_for_user,
    request_payout,
)
from core.models import SiteConfiguration
from events.models import Event, EventType


def make_ambassador(user):
    profile = OrganizerProfile.for_user(user)
    profile.grant_ambassador()
    profile.save(update_fields=["is_ambassador", "became_ambassador_at", "updated_at"])
    return profile


class AmbassadorEssentialsTests(TestCase):
    """Points 1 a 3 : code/lien, remise unique, commissions qui continuent."""

    def setUp(self):
        cache.clear()
        self.event_type, _ = EventType.objects.get_or_create(
            code="wedding", defaults={"label": "Mariage", "sort_order": 1}
        )
        config = SiteConfiguration.current()
        config.commission_mode = "percent"
        config.commission_referral_percent = Decimal("10")
        config.referral_duration_days = 365
        config.save()

        self.ambassador = get_user_model().objects.create_user(
            username="amb-essentiel", password="secret"
        )
        self.ambassador_profile = make_ambassador(self.ambassador)
        self.referred = get_user_model().objects.create_user(
            username="filleul-essentiel", password="secret"
        )
        OrganizerProfile.for_user(self.referred).attach_referrer(self.ambassador)

    def _paid_event(self, title, price=7900):
        return Event.objects.create(
            organizer=self.referred,
            title=title,
            event_type=self.event_type,
            event_date=date(2026, 9, 1),
            payment_status=Event.PaymentStatus.PAID,
            price_amount=price,
            price_currency="USD",
        )

    def test_1_ambassador_has_a_code_and_a_referral_link(self):
        self.client.force_login(self.ambassador)
        response = self.client.get(reverse("dashboard:home"))

        self.assertContains(response, self.ambassador_profile.referral_code)
        self.assertContains(response, f"parrain={self.ambassador_profile.referral_code}")
        self.assertEqual(len(self.ambassador_profile.referral_code), 8)

    def test_2_welcome_discount_applies_only_once(self):
        first = Event.objects.create(
            organizer=self.referred,
            title="Premier",
            event_type=self.event_type,
            event_date=date(2026, 9, 1),
        )
        self.assertTrue(first.has_discount)

        first.payment_status = Event.PaymentStatus.PAID
        first.save()

        second = Event.objects.create(
            organizer=self.referred,
            title="Deuxieme",
            event_type=self.event_type,
            event_date=date(2026, 10, 1),
        )
        third = Event.objects.create(
            organizer=self.referred,
            title="Troisieme",
            event_type=self.event_type,
            event_date=date(2026, 11, 1),
        )
        self.assertFalse(second.has_discount)
        self.assertFalse(third.has_discount)

    def test_3_ambassador_keeps_earning_on_every_later_event(self):
        """La remise est unique, la commission ne l'est pas."""
        for index in range(1, 4):
            self._paid_event(f"Evenement {index}")

        entries = CommissionLedger.objects.filter(
            beneficiary=self.ambassador, kind=CommissionLedger.Kind.REFERRAL_EVENT
        )
        self.assertEqual(entries.count(), 3)
        self.assertEqual(sum(entry.amount for entry in entries), 3 * 790)


class ReferralExpiryTests(TestCase):
    """Point 6 : l'affiliation dure un an, puis le filleul part."""

    def setUp(self):
        cache.clear()
        self.event_type, _ = EventType.objects.get_or_create(
            code="wedding", defaults={"label": "Mariage", "sort_order": 1}
        )
        config = SiteConfiguration.current()
        config.commission_mode = "percent"
        config.commission_referral_percent = Decimal("10")
        config.referral_duration_days = 365
        config.save()

        self.ambassador = get_user_model().objects.create_user(
            username="amb-expiry", password="secret"
        )
        make_ambassador(self.ambassador)
        self.referred = get_user_model().objects.create_user(
            username="filleul-expiry", password="secret"
        )
        self.profile = OrganizerProfile.for_user(self.referred)
        self.profile.attach_referrer(self.ambassador)

    def _age_referral(self, days):
        self.profile.referred_at = timezone.now() - timedelta(days=days)
        self.profile.save(update_fields=["referred_at", "updated_at"])
        self.profile.refresh_from_db()

    def _paid_event(self, title):
        return Event.objects.create(
            organizer=self.referred,
            title=title,
            event_type=self.event_type,
            event_date=date(2026, 9, 1),
            payment_status=Event.PaymentStatus.PAID,
            price_amount=7900,
            price_currency="USD",
        )

    def test_referral_is_active_within_the_year(self):
        self._age_referral(200)
        self.assertTrue(self.profile.referral_is_active)
        # Fourchette et non egalite stricte : le compte de jours tombe pile sur
        # une frontiere (365 - 200), et l'arrondi depend de l'heure d'execution.
        self.assertIn(self.profile.referral_days_remaining, (164, 165))

    def test_referral_expires_after_the_configured_duration(self):
        self._age_referral(366)
        self.assertFalse(self.profile.referral_is_active)
        self.assertEqual(self.profile.referral_days_remaining, 0)

    def test_no_referral_commission_once_expired(self):
        self._age_referral(400)
        self._paid_event("Apres expiration")

        self.assertFalse(
            CommissionLedger.objects.filter(
                beneficiary=self.ambassador, kind=CommissionLedger.Kind.REFERRAL_EVENT
            ).exists()
        )

    def test_duration_zero_means_lifetime(self):
        config = SiteConfiguration.current()
        config.referral_duration_days = 0
        config.save()
        cache.clear()

        self._age_referral(5000)
        self.assertTrue(self.profile.referral_is_active)
        self.assertIsNone(self.profile.referral_expires_at)

    def test_dashboard_counts_only_active_referrals(self):
        self._age_referral(400)
        self.client.force_login(self.ambassador)
        response = self.client.get(reverse("dashboard:home"))

        panel = response.context["earnings_panel"]
        self.assertEqual(panel["referred_count"], 0)
        self.assertEqual(panel["referred_expired_count"], 1)


class EarningsTrendTests(TestCase):
    """Point 4 : le tableau de bord montre l'evolution des gains."""

    def setUp(self):
        cache.clear()
        self.event_type, _ = EventType.objects.get_or_create(
            code="wedding", defaults={"label": "Mariage", "sort_order": 1}
        )
        self.ambassador = get_user_model().objects.create_user(
            username="amb-trend", password="secret"
        )
        make_ambassador(self.ambassador)

    def _commission(self, amount, months_ago):
        event = Event.objects.create(
            organizer=self.ambassador,
            title=f"Evenement {amount}-{months_ago}",
            event_type=self.event_type,
            event_date=date(2026, 9, 1),
            price_amount=7900,
            price_currency="USD",
        )
        entry = CommissionLedger.objects.create(
            beneficiary=self.ambassador,
            event=event,
            kind=CommissionLedger.Kind.OWN_EVENT,
            amount=amount,
            currency="USD",
        )
        CommissionLedger.objects.filter(pk=entry.pk).update(
            created_at=timezone.now() - timedelta(days=30 * months_ago)
        )
        return entry

    def test_monthly_series_is_chronological_with_relative_heights(self):
        self._commission(1000, months_ago=2)
        self._commission(4000, months_ago=0)

        series = monthly_earnings_for_user(self.ambassador)

        self.assertEqual(len(series), 2)
        self.assertEqual([row["amount"] for row in series], [1000, 4000])
        self.assertEqual(series[-1]["height_percent"], 100)  # le mois le plus fort
        self.assertLess(series[0]["height_percent"], 100)

    def test_dashboard_renders_the_trend(self):
        self._commission(2500, months_ago=1)
        self.client.force_login(self.ambassador)

        response = self.client.get(reverse("dashboard:home"))
        self.assertContains(response, "Évolution de vos gains")
        self.assertContains(response, "earnings-trend__bar")


class PayoutRequestTests(TestCase):
    """Point 5 : demande de retrait des gains."""

    def setUp(self):
        cache.clear()
        self.event_type, _ = EventType.objects.get_or_create(
            code="wedding", defaults={"label": "Mariage", "sort_order": 1}
        )
        config = SiteConfiguration.current()
        config.minimum_payout_amount = 2000
        config.save()

        self.ambassador = get_user_model().objects.create_user(
            username="amb-payout", password="secret"
        )
        make_ambassador(self.ambassador)

    def _commission(self, amount):
        event = Event.objects.create(
            organizer=self.ambassador,
            title=f"Evenement {amount}",
            event_type=self.event_type,
            event_date=date(2026, 9, 1),
            price_amount=7900,
            price_currency="USD",
        )
        return CommissionLedger.objects.create(
            beneficiary=self.ambassador,
            event=event,
            kind=CommissionLedger.Kind.OWN_EVENT,
            amount=amount,
            currency="USD",
        )

    def test_request_locks_the_available_commissions(self):
        self._commission(1500)
        self._commission(1200)

        payout = request_payout(self.ambassador, PayoutRequest.Method.MOBILE_MONEY, "+243...")

        self.assertEqual(payout.amount, 2700)
        self.assertEqual(payout.status, PayoutRequest.Status.PENDING)
        self.assertEqual(payout.commissions.count(), 2)
        # Plus rien de disponible : l'argent est engage.
        self.assertEqual(commission_summary_for_user(self.ambassador)["available_amount"], 0)

    def test_request_below_minimum_is_refused(self):
        self._commission(500)

        with self.assertRaises(ValueError) as ctx:
            request_payout(self.ambassador, PayoutRequest.Method.MOBILE_MONEY, "+243...")
        self.assertIn("minimum", str(ctx.exception))

    def test_second_open_request_is_refused(self):
        self._commission(3000)
        request_payout(self.ambassador, PayoutRequest.Method.MOBILE_MONEY, "+243...")
        self._commission(3000)

        with self.assertRaises(ValueError) as ctx:
            request_payout(self.ambassador, PayoutRequest.Method.MOBILE_MONEY, "+243...")
        self.assertIn("déjà une demande", str(ctx.exception))

    def test_marking_paid_settles_the_commissions(self):
        self._commission(3000)
        payout = request_payout(self.ambassador, PayoutRequest.Method.MOBILE_MONEY, "+243...")

        payout.mark_paid()

        payout.refresh_from_db()
        self.assertEqual(payout.status, PayoutRequest.Status.PAID)
        summary = commission_summary_for_user(self.ambassador)
        self.assertEqual(summary["paid_amount"], 3000)
        self.assertEqual(summary["pending_amount"], 0)

    def test_rejecting_releases_the_commissions(self):
        self._commission(3000)
        payout = request_payout(self.ambassador, PayoutRequest.Method.MOBILE_MONEY, "+243...")

        payout.reject("Coordonnées invalides")

        payout.refresh_from_db()
        self.assertEqual(payout.status, PayoutRequest.Status.REJECTED)
        # L'argent redevient demandable.
        self.assertEqual(commission_summary_for_user(self.ambassador)["available_amount"], 3000)

    def test_dashboard_form_creates_the_request(self):
        self._commission(4000)
        self.client.force_login(self.ambassador)

        response = self.client.post(
            reverse("accounts:request_payout"),
            {"method": PayoutRequest.Method.MOBILE_MONEY, "payout_details": "+243 999 000"},
        )

        self.assertEqual(response.status_code, 302)
        payout = PayoutRequest.objects.get(beneficiary=self.ambassador)
        self.assertEqual(payout.amount, 4000)
        self.assertEqual(payout.payout_details, "+243 999 000")

    def test_non_ambassador_cannot_request_a_payout(self):
        simple = get_user_model().objects.create_user(username="simple-payout", password="secret")
        self.client.force_login(simple)

        response = self.client.post(
            reverse("accounts:request_payout"),
            {"method": PayoutRequest.Method.MOBILE_MONEY, "payout_details": "+243 999 000"},
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(PayoutRequest.objects.filter(beneficiary=simple).exists())

    def test_details_are_required(self):
        self._commission(4000)
        self.client.force_login(self.ambassador)

        response = self.client.post(
            reverse("accounts:request_payout"),
            {"method": PayoutRequest.Method.MOBILE_MONEY, "payout_details": "  "},
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(PayoutRequest.objects.exists())
