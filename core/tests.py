from pathlib import Path
import base64
import os
import tempfile
from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from memora import settings as memora_settings
from events.models import Event, EventType
from processing.models import GeneratedMovie

from .checks import storage_configuration_check


class HomePageTests(SimpleTestCase):
    def test_home_page_returns_success(self):
        response = self.client.get(reverse("core:home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Memora")


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
        self.assertContains(response, "Film pret")
        self.assertContains(response, "Votre film souvenir est disponible.")


class HealthPageTests(SimpleTestCase):
    def test_health_page_returns_success(self):
        response = self.client.get(reverse("core:health"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"ok")


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
