from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import CommissionLedger, OrganizerProfile
from accounts.services import record_event_commissions
from core.models import SiteConfiguration
from events.models import Event, EventType


def make_paid_event(organizer, event_type, title="Evenement"):
    return Event.objects.create(
        organizer=organizer,
        title=title,
        event_type=event_type,
        event_date=date(2026, 7, 8),
        payment_status=Event.PaymentStatus.PAID,
    )


def make_ambassador(user):
    """Le statut est accorde par Memora : les tests de commissions doivent l'accorder."""
    profile = OrganizerProfile.for_user(user)
    profile.grant_ambassador()
    profile.save(update_fields=["is_ambassador", "became_ambassador_at", "updated_at"])
    return profile


def configure(**fields):
    """Met à jour le SiteConfiguration singleton (seedé par migration) sans en créer un second."""
    config = SiteConfiguration.objects.first() or SiteConfiguration.objects.create()
    for key, value in fields.items():
        setattr(config, key, value)
    config.save()
    return config


class OrganizerProfileSignalTests(TestCase):
    def test_profile_created_on_user_creation(self):
        user = get_user_model().objects.create_user(username="alice", password="secret")
        profile = OrganizerProfile.objects.filter(user=user).first()
        self.assertIsNotNone(profile)
        self.assertTrue(profile.referral_code)
        self.assertEqual(profile.tier, OrganizerProfile.Tier.STARTER)

    def test_referral_codes_are_unique(self):
        u1 = get_user_model().objects.create_user(username="a", password="secret")
        u2 = get_user_model().objects.create_user(username="b", password="secret")
        self.assertNotEqual(u1.organizer_profile.referral_code, u2.organizer_profile.referral_code)


class OrganizerSignupTests(TestCase):
    def test_signup_creates_and_logs_in_organizer(self):
        response = self.client.post(
            reverse("accounts:signup"),
            {
                "username": "organizer",
                "email": "organizer@example.com",
                "password1": "a-strong-test-password-42",
                "password2": "a-strong-test-password-42",
            },
        )

        self.assertRedirects(response, reverse("dashboard:home"))
        self.assertTrue(get_user_model().objects.filter(username="organizer").exists())
        self.assertIn("_auth_user_id", self.client.session)

    def test_signup_with_valid_referral_code_links_referrer(self):
        referrer = get_user_model().objects.create_user(username="parrain", password="secret")
        code = referrer.organizer_profile.referral_code

        self.client.post(
            reverse("accounts:signup"),
            {
                "username": "filleul",
                "email": "filleul@example.com",
                "password1": "a-strong-test-password-42",
                "password2": "a-strong-test-password-42",
                "referral_code": code.lower(),
            },
        )

        filleul = get_user_model().objects.get(username="filleul")
        self.assertEqual(filleul.organizer_profile.referred_by, referrer)

    def test_signup_with_unknown_referral_code_is_rejected(self):
        response = self.client.post(
            reverse("accounts:signup"),
            {
                "username": "filleul",
                "email": "filleul@example.com",
                "password1": "a-strong-test-password-42",
                "password2": "a-strong-test-password-42",
                "referral_code": "ZZZZZZZZ",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ce code de parrainage est inconnu.")
        self.assertFalse(get_user_model().objects.filter(username="filleul").exists())

    def test_signup_prefills_referral_code_from_query(self):
        referrer = get_user_model().objects.create_user(username="parrain", password="secret")
        code = referrer.organizer_profile.referral_code

        response = self.client.get(reverse("accounts:signup") + f"?parrain={code}")

        self.assertContains(response, code)


class OwnEventCommissionTests(TestCase):
    def setUp(self):
        self.event_type, _ = EventType.objects.get_or_create(
            code="wedding", defaults={"label": "Mariage", "sort_order": 1}
        )
        self.organizer = get_user_model().objects.create_user(username="orga", password="secret")
        make_ambassador(self.organizer)
        self.config = configure(
            commission_starter_amount=500,
            commission_medium_amount=1000,
            commission_premium_amount=2000,
            tier_medium_min_events=51,
            tier_premium_min_events=101,
            commission_referral_amount=500,
        )

    def test_first_paid_event_earns_starter_amount(self):
        event = make_paid_event(self.organizer, self.event_type)
        entry = CommissionLedger.objects.get(event=event, kind=CommissionLedger.Kind.OWN_EVENT)
        self.assertEqual(entry.beneficiary, self.organizer)
        self.assertEqual(entry.amount, 500)
        self.assertEqual(entry.tier, "starter")
        self.assertEqual(entry.status, CommissionLedger.Status.PENDING)

    def test_commission_is_idempotent_on_resave(self):
        event = make_paid_event(self.organizer, self.event_type)
        event.save()
        event.save()
        self.assertEqual(
            CommissionLedger.objects.filter(event=event, kind=CommissionLedger.Kind.OWN_EVENT).count(),
            1,
        )

    def test_tier_amount_follows_paid_count(self):
        # 50 événements déjà payés (starter), le 51e bascule en medium.
        Event.objects.bulk_create(
            [
                Event(
                    organizer=self.organizer,
                    title=f"E{i}",
                    slug=f"e-{i}",
                    public_access_key=f"key-{i}",
                    event_type=self.event_type,
                    event_date=date(2026, 7, 8),
                    payment_status=Event.PaymentStatus.PAID,
                    price_amount=5900,
                    price_currency="USD",
                )
                for i in range(50)
            ]
        )
        # 51e événement payé -> palier medium, 1000 centimes.
        event = make_paid_event(self.organizer, self.event_type, title="Cinquante-et-un")
        entry = CommissionLedger.objects.get(event=event, kind=CommissionLedger.Kind.OWN_EVENT)
        self.assertEqual(entry.tier, "medium")
        self.assertEqual(entry.amount, 1000)

    def test_profile_tier_updates_after_payment(self):
        make_paid_event(self.organizer, self.event_type)
        self.organizer.organizer_profile.refresh_from_db()
        self.assertEqual(self.organizer.organizer_profile.tier, OrganizerProfile.Tier.STARTER)

    def test_zero_amount_creates_no_commission(self):
        self.config.commission_starter_amount = 0
        self.config.save()
        event = make_paid_event(self.organizer, self.event_type)
        self.assertFalse(
            CommissionLedger.objects.filter(event=event, kind=CommissionLedger.Kind.OWN_EVENT).exists()
        )

    def test_unpaid_event_creates_no_commission(self):
        event = Event.objects.create(
            organizer=self.organizer,
            title="Non paye",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
        )
        self.assertFalse(CommissionLedger.objects.filter(event=event).exists())


class ReferralCommissionTests(TestCase):
    def setUp(self):
        self.event_type, _ = EventType.objects.get_or_create(
            code="wedding", defaults={"label": "Mariage", "sort_order": 1}
        )
        configure(
            commission_starter_amount=500,
            commission_medium_amount=1000,
            commission_premium_amount=2000,
            commission_referral_amount=500,
        )
        self.referrer = get_user_model().objects.create_user(username="parrain", password="secret")
        make_ambassador(self.referrer)
        self.referred = get_user_model().objects.create_user(username="filleul", password="secret")
        profile = self.referred.organizer_profile
        profile.referred_by = self.referrer
        profile.save(update_fields=["referred_by"])

    def test_referrer_earns_on_each_paid_event_of_referred(self):
        make_paid_event(self.referred, self.event_type, title="Un")
        make_paid_event(self.referred, self.event_type, title="Deux")

        referral_entries = CommissionLedger.objects.filter(
            beneficiary=self.referrer, kind=CommissionLedger.Kind.REFERRAL_EVENT
        )
        self.assertEqual(referral_entries.count(), 2)
        self.assertTrue(all(entry.amount == 500 for entry in referral_entries))

    def test_no_referral_commission_without_referrer(self):
        solo = get_user_model().objects.create_user(username="solo", password="secret")
        make_paid_event(solo, self.event_type)
        self.assertFalse(
            CommissionLedger.objects.filter(kind=CommissionLedger.Kind.REFERRAL_EVENT).exists()
        )

    def test_referral_commission_is_idempotent(self):
        event = make_paid_event(self.referred, self.event_type)
        event.save()
        self.assertEqual(
            CommissionLedger.objects.filter(
                event=event, kind=CommissionLedger.Kind.REFERRAL_EVENT
            ).count(),
            1,
        )


class DashboardEarningsPanelTests(TestCase):
    def setUp(self):
        self.event_type, _ = EventType.objects.get_or_create(
            code="wedding", defaults={"label": "Mariage", "sort_order": 1}
        )
        configure(
            commission_starter_amount=500,
            commission_referral_amount=500,
        )
        self.organizer = get_user_model().objects.create_user(username="orga", password="secret")
        make_ambassador(self.organizer)

    def test_dashboard_shows_tier_and_rate(self):
        self.client.force_login(self.organizer)
        response = self.client.get(reverse("dashboard:home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Mes gains")
        self.assertContains(response, "Starter")
        self.assertContains(response, self.organizer.organizer_profile.referral_code)

    def test_dashboard_reflects_earned_commission(self):
        make_paid_event(self.organizer, self.event_type)
        self.client.force_login(self.organizer)
        response = self.client.get(reverse("dashboard:home"))
        self.assertContains(response, "par événement payé")


class AmbassadorGatingTests(TestCase):
    """Le programme est reserve aux ambassadeurs designes par Memora."""

    def setUp(self):
        self.event_type, _ = EventType.objects.get_or_create(
            code="wedding", defaults={"label": "Mariage", "sort_order": 1}
        )
        configure(commission_starter_amount=500, commission_referral_amount=500)
        self.organizer = get_user_model().objects.create_user(username="simple", password="secret")

    def test_new_organizers_are_not_ambassadors(self):
        self.assertFalse(self.organizer.organizer_profile.is_ambassador)

    def test_simple_organizer_earns_nothing(self):
        make_paid_event(self.organizer, self.event_type)
        self.assertFalse(CommissionLedger.objects.filter(beneficiary=self.organizer).exists())

    def test_simple_organizer_sees_no_earnings_panel(self):
        self.client.force_login(self.organizer)
        response = self.client.get(reverse("dashboard:home"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Mes gains")
        self.assertNotContains(response, "lien de parrainage")

    def test_referral_pays_nothing_when_referrer_is_not_ambassador(self):
        referred = get_user_model().objects.create_user(username="filleul", password="secret")
        profile = referred.organizer_profile
        profile.referred_by = self.organizer
        profile.save(update_fields=["referred_by"])

        make_paid_event(referred, self.event_type)

        self.assertFalse(
            CommissionLedger.objects.filter(kind=CommissionLedger.Kind.REFERRAL_EVENT).exists()
        )

    def test_granting_status_starts_the_commissions(self):
        make_paid_event(self.organizer, self.event_type, title="Avant")
        self.assertFalse(CommissionLedger.objects.filter(beneficiary=self.organizer).exists())

        make_ambassador(self.organizer)
        make_paid_event(self.organizer, self.event_type, title="Apres")

        entries = CommissionLedger.objects.filter(beneficiary=self.organizer)
        # Seul l'evenement paye apres l'octroi est commissionne : pas de rattrapage.
        self.assertEqual(entries.count(), 1)
        self.assertEqual(entries.first().event.title, "Apres")

    def test_revoking_keeps_commissions_already_earned(self):
        make_ambassador(self.organizer)
        make_paid_event(self.organizer, self.event_type)
        self.assertEqual(CommissionLedger.objects.filter(beneficiary=self.organizer).count(), 1)

        profile = self.organizer.organizer_profile
        profile.revoke_ambassador()
        profile.save(update_fields=["is_ambassador", "updated_at"])

        # On ne reecrit pas le passe : ce qui est du reste du.
        self.assertEqual(CommissionLedger.objects.filter(beneficiary=self.organizer).count(), 1)
