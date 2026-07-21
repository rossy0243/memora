from pathlib import Path
import base64
import os
import tempfile
from datetime import date
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from memora import settings as memora_settings
from events.models import Event, EventType
from processing.models import GeneratedMovie

from .checks import storage_configuration_check
from .models import SiteConfiguration


class HomePageTests(TestCase):
    def test_home_page_returns_success(self):
        response = self.client.get(reverse("core:home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Memora")
        self.assertContains(response, "Memora ne se contente pas de stocker des photos.")
        self.assertContains(response, "Une caméra pensée pour les invités")
        self.assertContains(response, "Une collecte maîtrisée")
        self.assertContains(response, "Un film préparé automatiquement")
        self.assertContains(response, "59 USD")
        self.assertContains(response, "par événement")
        self.assertContains(response, "og:title")
        self.assertContains(response, "twitter:card")
        self.assertContains(response, "canonical")
        self.assertContains(response, "img/memora-mark.svg")

    def test_home_page_uses_admin_event_price(self):
        site_configuration = SiteConfiguration.current()
        site_configuration.event_price_amount = 7900
        site_configuration.event_price_currency = "EUR"
        site_configuration.save()

        response = self.client.get(reverse("core:home"))

        self.assertContains(response, "79 EUR")
        self.assertNotContains(response, "59 USD")

    def test_home_shows_ambassador_program_teaser(self):
        response = self.client.get(reverse("core:home"))

        self.assertContains(response, "Programme Ambassadeur")
        self.assertContains(response, reverse("core:ambassador_program"))


class AmbassadorProgramPageTests(TestCase):
    def test_page_renders_with_dynamic_amounts(self):
        config = SiteConfiguration.current()
        config.event_price_currency = "USD"
        config.commission_starter_amount = 500
        config.commission_medium_amount = 1000
        config.commission_premium_amount = 2000
        config.commission_referral_amount = 500
        config.tier_medium_min_events = 51
        config.tier_premium_min_events = 101
        config.save()

        response = self.client.get(reverse("core:ambassador_program"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Programme Ambassadeur")
        self.assertContains(response, "5 USD")
        self.assertContains(response, "10 USD")
        self.assertContains(response, "20 USD")
        self.assertContains(response, "Jusqu'à 50 événements")
        self.assertContains(response, "De 51 à 100 événements")
        self.assertContains(response, "Plus de 100 événements")

    def test_page_is_reachable_without_login(self):
        response = self.client.get(reverse("core:ambassador_program"))
        self.assertEqual(response.status_code, 200)


class LegalPagesTests(TestCase):
    def _configure(self, **fields):
        config = SiteConfiguration.current()
        for key, value in fields.items():
            setattr(config, key, value)
        config.save()
        return config

    def test_terms_page_renders_with_dynamic_values(self):
        self._configure(
            company_name="Memora",
            legal_entity_name="Memora SAS",
            legal_contact_email="legal@memora.test",
            legal_country="France",
            legal_registration_number="RCS Paris 123 456 789",
            payment_provider_name="Stripe",
            refund_window_days=30,
            cgu_effective_date=date(2026, 1, 15),
        )
        response = self.client.get(reverse("core:terms"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Conditions Générales d'Utilisation")
        self.assertContains(response, "Memora SAS")
        self.assertContains(response, "legal@memora.test")
        self.assertContains(response, "France")
        self.assertContains(response, "15/01/2026")
        self.assertContains(response, "RCS Paris 123 456 789")
        self.assertContains(response, "Stripe")
        self.assertContains(response, "30 jours")
        self.assertContains(response, "remboursement", status_code=200)
        self.assertContains(response, "paiement")

    def test_privacy_page_renders_with_dynamic_values(self):
        self._configure(
            legal_entity_name="Memora SAS",
            legal_contact_email="legal@memora.test",
            payment_provider_name="Stripe",
            data_protection_authority="la CNIL",
            privacy_effective_date=date(2026, 2, 20),
        )
        response = self.client.get(reverse("core:privacy"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Politique de confidentialité")
        self.assertContains(response, "Memora SAS")
        self.assertContains(response, "20/02/2026")
        self.assertContains(response, "Stripe")
        self.assertContains(response, "la CNIL")

    def test_data_protection_authority_has_generic_fallback(self):
        self._configure(data_protection_authority="")
        response = self.client.get(reverse("core:privacy"))
        self.assertContains(response, "autorité de protection des données compétente")

    def test_entity_name_falls_back_to_company_name(self):
        self._configure(company_name="MonProduit", legal_entity_name="")
        response = self.client.get(reverse("core:terms"))
        self.assertContains(response, "MonProduit")

    def test_company_name_is_dynamic_in_footer(self):
        self._configure(company_name="MarquePerso")
        response = self.client.get(reverse("core:home"))
        self.assertContains(response, "MarquePerso")

    def test_footer_links_to_legal_pages(self):
        response = self.client.get(reverse("core:home"))
        self.assertContains(response, reverse("core:terms"))
        self.assertContains(response, reverse("core:privacy"))

    def test_legal_pages_are_public(self):
        for name in ("core:terms", "core:privacy"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200)


class AuthenticatedHomePageTests(TestCase):
    def test_authenticated_organizer_is_redirected_to_dashboard(self):
        user = get_user_model().objects.create_user(
            username="organizer",
            email="organizer@example.com",
            password="secret",
        )
        self.client.force_login(user)

        response = self.client.get(reverse("core:home"))

        self.assertRedirects(response, reverse("dashboard:home"))


class DashboardHomeTests(TestCase):
    def test_empty_dashboard_has_single_create_event_call_to_action(self):
        user = get_user_model().objects.create_user(
            username="organizer",
            email="organizer@example.com",
            password="secret",
        )
        self.client.force_login(user)

        response = self.client.get(reverse("dashboard:home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("events:create"), count=1)

    def test_dashboard_home_displays_post_event_movie_status(self):
        user = get_user_model().objects.create_user(
            username="organizer",
            email="organizer@example.com",
            password="secret",
        )
        event_type = EventType.objects.get(code="wedding")
        event = Event.objects.create(
            organizer=user,
            title="Mariage termine",
            event_type=event_type,
            event_date=date(2026, 7, 8),
        )
        GeneratedMovie.objects.create(
            event=event,
            status=GeneratedMovie.Status.COMPLETED,
            final_file="events/mariage/movies/memora.mp4",
        )
        self.client.force_login(user)

        response = self.client.get(reverse("dashboard:home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Film prêt")
        self.assertContains(response, "Votre film souvenir est disponible.")


class HealthPageTests(SimpleTestCase):
    def test_health_page_returns_success(self):
        response = self.client.get(reverse("core:health"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"ok")


class SeoEndpointTests(SimpleTestCase):
    def test_robots_txt_exposes_sitemap_and_blocks_private_areas(self):
        response = self.client.get(reverse("core:robots"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sitemap:")
        self.assertContains(response, "Disallow: /admin/")
        self.assertContains(response, "Disallow: /dashboard/")
        self.assertContains(response, "Disallow: /evenements/")

    def test_sitemap_xml_lists_public_landing_only(self):
        response = self.client.get(reverse("core:sitemap"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<urlset")
        self.assertContains(response, reverse("core:home"))
        self.assertContains(response, reverse("core:ambassador_program"))
        self.assertNotContains(response, "/dashboard/")


class LoggingSettingsTests(SimpleTestCase):
    def test_application_logging_is_configured_for_console_output(self):
        self.assertIn("console", memora_settings.LOGGING["handlers"])
        self.assertEqual(memora_settings.LOGGING["root"]["handlers"], ["console"])
        self.assertIn("processing", memora_settings.LOGGING["loggers"])
        self.assertIn("uploads", memora_settings.LOGGING["loggers"])


class BackupDatabaseCommandTests(SimpleTestCase):
    @override_settings(
        DATABASES={
            "default": {
                "ENGINE": "django.db.backends.postgresql",
                "NAME": "memora",
                "USER": "memora_user",
                "PASSWORD": "secret-password",
                "HOST": "localhost",
                "PORT": "5432",
            }
        }
    )
    @patch("core.management.commands.backup_database.subprocess.run")
    @patch("core.management.commands.backup_database.shutil.which", return_value="pg_dump")
    def test_backup_database_runs_pg_dump_without_leaking_password(self, _which, run):
        run.return_value.returncode = 0
        run.return_value.stdout = ""
        run.return_value.stderr = ""

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "memora.dump"
            call_command("backup_database", "--output", str(output_path))

        command = run.call_args.args[0]
        env = run.call_args.kwargs["env"]
        self.assertIn("--file", command)
        self.assertIn(str(output_path), command)
        self.assertNotIn("secret-password", command)
        self.assertEqual(env["PGPASSWORD"], "secret-password")

    @override_settings(DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": "db.sqlite3"}})
    @patch("core.management.commands.backup_database.shutil.which", return_value="pg_dump")
    def test_backup_database_rejects_non_postgresql_database(self, _which):
        output = StringIO()

        with self.assertRaisesMessage(Exception, "PostgreSQL"):
            call_command("backup_database", stdout=output)


class StorageConfigurationCheckTests(SimpleTestCase):
    @override_settings(MEMORA_STORAGE_BACKEND="local")
    def test_local_storage_configuration_is_valid(self):
        self.assertEqual(storage_configuration_check(None), [])

    @override_settings(MEMORA_STORAGE_BACKEND="ftp")
    def test_rejects_unknown_storage_backend(self):
        errors = storage_configuration_check(None)

        self.assertEqual(errors[0].id, "memora.E001")

    @override_settings(
        MEMORA_STORAGE_BACKEND="s3",
        STORAGES={
            "default": {
                "OPTIONS": {
                    "access_key": "",
                    "secret_key": "",
                    "bucket_name": "",
                }
            }
        },
    )
    def test_s3_storage_requires_credentials_and_bucket(self):
        errors = storage_configuration_check(None)

        self.assertEqual(len(errors), 3)
        self.assertTrue(all(error.id == "memora.E002" for error in errors))


class GoogleCredentialsSettingsTests(SimpleTestCase):
    def test_google_credentials_json_is_materialized_to_temp_file(self):
        credentials = '{"type":"service_account","project_id":"memora-test"}'
        previous_credentials_path = os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)

        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                with patch.dict(os.environ, {"GOOGLE_APPLICATION_CREDENTIALS_JSON": credentials}, clear=False):
                    with patch("memora.settings.tempfile.gettempdir", return_value=temp_dir):
                        memora_settings.materialize_google_application_credentials()

                    credentials_path = Path(os.environ["GOOGLE_APPLICATION_CREDENTIALS"])
                    self.assertTrue(credentials_path.exists())
                    self.assertEqual(credentials_path.read_text(encoding="utf-8"), credentials)
        finally:
            os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)
            os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS_JSON", None)
            if previous_credentials_path:
                os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = previous_credentials_path

    def test_google_credentials_base64_is_materialized_to_temp_file(self):
        credentials = '{"type":"service_account","project_id":"memora-test"}'
        encoded_credentials = base64.b64encode(credentials.encode("utf-8")).decode("ascii")
        previous_credentials_path = os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)

        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                with patch.dict(os.environ, {"GOOGLE_APPLICATION_CREDENTIALS_B64": encoded_credentials}, clear=False):
                    os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS_JSON", None)
                    with patch("memora.settings.tempfile.gettempdir", return_value=temp_dir):
                        memora_settings.materialize_google_application_credentials()

                    credentials_path = Path(os.environ["GOOGLE_APPLICATION_CREDENTIALS"])
                    self.assertTrue(credentials_path.exists())
                    self.assertEqual(credentials_path.read_text(encoding="utf-8"), credentials)
        finally:
            os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)
            os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS_B64", None)
            if previous_credentials_path:
                os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = previous_credentials_path
