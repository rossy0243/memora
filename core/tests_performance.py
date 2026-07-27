"""Session, cache et cookies : comportements de performance et de securite."""
import time

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from core.middleware import LAST_ACTIVITY_KEY
from core.models import SITE_CONFIGURATION_CACHE_KEY, SiteConfiguration
from events.models import EventPlan


class ConfigurationCacheTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_current_is_read_from_database_only_once(self):
        SiteConfiguration.current()  # amorce le cache
        with self.assertNumQueries(0):
            SiteConfiguration.current()
            SiteConfiguration.current()

    def test_saving_configuration_invalidates_the_cache(self):
        SiteConfiguration.current()
        configuration = SiteConfiguration.objects.first() or SiteConfiguration.objects.create()
        configuration.event_price_amount = 12345
        configuration.save()

        self.assertIsNone(cache.get(SITE_CONFIGURATION_CACHE_KEY))
        self.assertEqual(SiteConfiguration.current().event_price_amount, 12345)

    def test_saving_a_plan_invalidates_the_plan_cache(self):
        from core.context_processors import ACTIVE_PLANS_CACHE_KEY, _active_event_plans

        _active_event_plans()
        self.assertIsNotNone(cache.get(ACTIVE_PLANS_CACHE_KEY))

        EventPlan.objects.create(code="nouveau", label="Nouveau", price_amount=1000)
        self.assertIsNone(cache.get(ACTIVE_PLANS_CACHE_KEY))
        self.assertIn("Nouveau", [plan.label for plan in _active_event_plans()])

    def test_home_page_does_not_requery_configuration_on_every_hit(self):
        """La page d'accueil est la plus vue : elle ne doit pas relire la config."""
        self.client.get(reverse("core:home"))  # amorce
        with self.assertNumQueries(0):
            self.client.get(reverse("core:home"))


class SessionIdleTimeoutTests(TestCase):
    def setUp(self):
        cache.clear()
        self.organizer = get_user_model().objects.create_user(
            username="orga-idle", password="secret"
        )

    @override_settings(MEMORA_SESSION_IDLE_TIMEOUT_SECONDS=1800)
    def test_active_organizer_stays_connected(self):
        self.client.force_login(self.organizer)
        response = self.client.get(reverse("dashboard:home"))
        self.assertEqual(response.status_code, 200)

    @override_settings(MEMORA_SESSION_IDLE_TIMEOUT_SECONDS=1800)
    def test_idle_organizer_is_logged_out_and_sent_to_login(self):
        self.client.force_login(self.organizer)
        self.client.get(reverse("dashboard:home"))

        # On recule l'horodatage d'activite au-dela du seuil.
        session = self.client.session
        session[LAST_ACTIVITY_KEY] = time.time() - 3600
        session.save()

        response = self.client.get(reverse("dashboard:home"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)
        # La session d'authentification est bien videe.
        self.assertNotIn("_auth_user_id", self.client.session)

    @override_settings(MEMORA_SESSION_IDLE_TIMEOUT_SECONDS=0)
    def test_timeout_can_be_disabled(self):
        self.client.force_login(self.organizer)
        session = self.client.session
        session[LAST_ACTIVITY_KEY] = time.time() - 99999
        session.save()

        response = self.client.get(reverse("dashboard:home"))
        self.assertEqual(response.status_code, 200)

    @override_settings(
        MEMORA_SESSION_IDLE_TIMEOUT_SECONDS=1800,
        MEMORA_SESSION_ACTIVITY_REFRESH_SECONDS=600,
    )
    def test_activity_stamp_is_not_rewritten_on_every_request(self):
        """Sinon chaque requete provoquerait une ecriture de session."""
        self.client.force_login(self.organizer)
        self.client.get(reverse("dashboard:home"))
        first_stamp = self.client.session[LAST_ACTIVITY_KEY]

        self.client.get(reverse("dashboard:home"))
        self.assertEqual(self.client.session[LAST_ACTIVITY_KEY], first_stamp)

    @override_settings(MEMORA_SESSION_IDLE_TIMEOUT_SECONDS=1800)
    def test_guest_sessions_are_never_expired_by_the_middleware(self):
        """La session invite porte son quota d'envois : la vider le remettrait a zero."""
        session = self.client.session
        session["guest_marker"] = "quota-invite"
        session[LAST_ACTIVITY_KEY] = time.time() - 99999
        session.save()

        response = self.client.get(reverse("core:home"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.session["guest_marker"], "quota-invite")


class ResponseOptimisationTests(TestCase):
    def test_html_response_is_compressed_when_accepted(self):
        response = self.client.get(
            reverse("core:home"),
            headers={"accept-encoding": "gzip, deflate"},
            # Le middleware ne compresse qu'au-dela de 200 octets : la home suffit.
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("Content-Encoding"), "gzip")

    def test_unchanged_page_answers_304(self):
        first = self.client.get(reverse("core:home"))
        etag = first.headers.get("ETag")
        self.assertIsNotNone(etag)

        second = self.client.get(reverse("core:home"), headers={"if-none-match": etag})
        self.assertEqual(second.status_code, 304)


class CookiePolicyTests(TestCase):
    def test_session_cookie_is_http_only_and_same_site(self):
        from django.conf import settings

        self.assertTrue(settings.SESSION_COOKIE_HTTPONLY)
        self.assertEqual(settings.SESSION_COOKIE_SAMESITE, "Lax")
        self.assertEqual(settings.CSRF_COOKIE_SAMESITE, "Lax")

    def test_guest_session_cookie_outlives_a_long_event(self):
        """Un cookie court redonnerait a chaque invite un quota d'envois neuf."""
        from django.conf import settings

        self.assertGreaterEqual(settings.SESSION_COOKIE_AGE, 60 * 60 * 24 * 7)
