from datetime import date, datetime, timedelta
from io import BytesIO, StringIO
from pathlib import Path
import shutil
import tempfile
from unittest.mock import patch
import zipfile
from xml.etree import ElementTree
from zipfile import ZipFile
import zlib

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from accounts.models import AgentProfile
from core.models import SiteConfiguration
from guestbook.models import GuestBookAssignment, GuestBookMessage, GuestBookMovie
from core.storage_errors import STORAGE_UNAVAILABLE_MESSAGE
from processing.models import GeneratedMovie
from uploads.models import GuestUpload, MomentTemplate, UploadCategory

from .brand_assets import ASSETS
from .models import Event, EventPlan, EventType
from .services import EventResetRefused, reset_event_content
from .qr_kit import (
    brand_contact_items,
    build_qr_kit_zip,
    landscape_layout,
    portrait_layout,
    qr_matrix,
    render_mask,
    square_layout,
)

TEST_MEDIA_ROOT = tempfile.mkdtemp()


class EventPlanTests(TestCase):
    """Formules : prix, quota de souvenirs, et tolerance au depassement."""

    def setUp(self):
        self.organizer = get_user_model().objects.create_user(
            username="orga-plan", password="secret"
        )
        self.event_type, _ = EventType.objects.get_or_create(
            code="wedding", defaults={"label": "Mariage", "sort_order": 1}
        )
        self.plan = EventPlan.objects.create(
            code="intime-test",
            label="Intime",
            max_guests=50,
            upload_quota=10,
            price_amount=4900,
        )

    def _event(self, plan=None):
        return Event.objects.create(
            organizer=self.organizer,
            title="Mariage formule",
            event_type=self.event_type,
            event_date=date(2026, 8, 1),
            plan=plan,
        )

    def _upload(self, event, index):
        category, _ = UploadCategory.objects.get_or_create(
            event=event,
            code="ceremony",
            defaults={"label": "Cérémonie", "sort_order": 1},
        )
        return GuestUpload.objects.create(
            event=event,
            category=category,
            media_type=GuestUpload.MediaType.IMAGE,
            media_file=f"events/test/uploads/p{index}.jpg",
            original_filename=f"p{index}.jpg",
            file_size=1024,
            moderation_status=GuestUpload.ModerationStatus.APPROVED,
        )

    def test_plan_sets_event_price(self):
        event = self._event(plan=self.plan)
        self.assertEqual(event.price_amount, 4900)

    def test_event_without_plan_falls_back_to_site_price(self):
        event = self._event()
        self.assertEqual(event.price_amount, SiteConfiguration.current().event_price_amount)

    def test_quota_state_tracks_usage(self):
        event = self._event(plan=self.plan)
        for index in range(8):
            self._upload(event, index)

        state = event.upload_quota_state
        self.assertEqual(state["quota"], 10)
        self.assertEqual(state["used"], 8)
        self.assertEqual(state["remaining"], 2)
        self.assertTrue(state["is_nearly_reached"])
        self.assertFalse(state["is_reached"])

    def test_grace_margin_lets_uploads_through_past_the_quota(self):
        """Un invite n'est jamais bloque net au quota : la marge absorbe le trop-plein."""
        from uploads.services import get_upload_limit_error

        configuration = SiteConfiguration.current()
        configuration.upload_quota_grace_percent = 20
        configuration.save(update_fields=["upload_quota_grace_percent"])

        event = self._event(plan=self.plan)
        for index in range(10):  # quota atteint
            self._upload(event, index)

        self.assertTrue(event.upload_quota_state["is_reached"])
        # ... mais on accepte encore jusqu'a 12 (quota + 20 %).
        self.assertEqual(event.upload_hard_limit, 12)
        self.assertEqual(get_upload_limit_error(event, "session-x", "10.0.0.1"), "")

        for index in range(10, 12):
            self._upload(event, index)
        message = get_upload_limit_error(event, "session-y", "10.0.0.2")
        self.assertIn("formule", message)


class EventModelTests(TestCase):
    def setUp(self):
        self.organizer = get_user_model().objects.create_user(
            username="organizer",
            email="organizer@example.com",
            password="secret",
        )
        self.event_type, _ = EventType.objects.get_or_create(
            code="wedding",
            defaults={
                "label": "Mariage",
                "sort_order": 1,
            },
        )

    def test_event_generates_slug_from_title(self):
        event = Event.objects.create(
            organizer=self.organizer,
            title="Mariage de Camille et Noe",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
        )

        self.assertEqual(event.slug, "mariage-de-camille-et-noe")

    def test_event_generates_unique_slug(self):
        Event.objects.create(
            organizer=self.organizer,
            title="Notre Mariage",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
        )
        second_event = Event.objects.create(
            organizer=self.organizer,
            title="Notre Mariage",
            event_type=self.event_type,
            event_date=date(2026, 7, 9),
        )

        self.assertEqual(second_event.slug, "notre-mariage-2")

    def test_event_normalizes_guest_access_code(self):
        event = Event.objects.create(
            organizer=self.organizer,
            title="Mariage prive",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
            guest_access_code="  amour2026  ",
        )

        self.assertEqual(event.guest_access_code, "AMOUR2026")
        self.assertTrue(event.requires_guest_access_code)
        self.assertTrue(event.check_guest_access_code("amour2026"))

    def test_event_builds_public_movie_url(self):
        event = Event.objects.create(
            organizer=self.organizer,
            title="Mariage Film",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
        )

        self.assertEqual(
            event.get_public_movie_url(),
            reverse(
                "public_movie",
                kwargs={"slug": event.slug, "access_key": event.public_access_key},
            ),
        )

    def test_event_public_access_key_is_not_guessable(self):
        event = Event.objects.create(
            organizer=self.organizer,
            title="Mariage Prive",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
        )

        self.assertGreaterEqual(len(event.public_access_key), 16)
        self.assertNotEqual(event.public_access_key, event.slug)

    def test_event_defaults_to_pending_manual_payment(self):
        event = Event.objects.create(
            organizer=self.organizer,
            title="Mariage a activer",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
        )

        self.assertEqual(event.payment_status, Event.PaymentStatus.PENDING)
        self.assertFalse(event.is_paid)
        self.assertFalse(event.can_accept_guest_uploads)
        self.assertEqual(event.price_amount, 5900)
        self.assertEqual(event.price_currency, "USD")
        self.assertEqual(event.formatted_price, "59 USD")

    def test_event_uses_admin_configured_default_price(self):
        site_configuration = SiteConfiguration.current()
        site_configuration.event_price_amount = 7900
        site_configuration.event_price_currency = "eur"
        site_configuration.save()

        event = Event.objects.create(
            organizer=self.organizer,
            title="Mariage avec nouveau prix",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
        )

        self.assertEqual(event.price_amount, 7900)
        self.assertEqual(event.price_currency, "EUR")
        self.assertEqual(event.formatted_price, "79 EUR")

    def test_event_can_be_marked_paid_manually(self):
        event = Event.objects.create(
            organizer=self.organizer,
            title="Mariage paye",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
        )

        event.mark_paid(reference="manual-001", provider="admin")
        event.save()

        self.assertTrue(event.is_paid)
        self.assertTrue(event.can_accept_guest_uploads)
        self.assertEqual(event.payment_reference, "manual-001")
        self.assertEqual(event.payment_provider, "admin")
        self.assertIsNotNone(event.paid_at)


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class EventViewTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="owner",
            email="owner@example.com",
            password="secret",
        )
        self.other_user = get_user_model().objects.create_user(
            username="other",
            email="other@example.com",
            password="secret",
        )
        self.event_type = EventType.objects.get(code="wedding")

    def mark_paid(self, event):
        event.mark_paid(provider="test")
        event.save(update_fields=["payment_status", "paid_at", "payment_provider"])
        return event

    def test_organizer_can_create_event(self):
        self.client.login(username="owner", password="secret")

        response = self.client.post(
            reverse("events:create"),
            {
                "title": "Mariage de Lea et Sam",
                "couple_name": "Lea & Sam",
                "event_type": self.event_type.pk,
                "event_date": "2026-07-08",
                "location": "Paris",
                "welcome_message": "Partagez vos plus beaux souvenirs.",
                "guest_access_code": "amour2026",
                "is_active": "on",
                "media_retention_days": "90",
            },
        )

        event = Event.objects.get(title="Mariage de Lea et Sam")
        self.assertRedirects(response, reverse("events:detail", kwargs={"pk": event.pk}))
        self.assertEqual(event.organizer, self.user)
        self.assertEqual(event.slug, "mariage-de-lea-et-sam")
        self.assertEqual(event.payment_status, Event.PaymentStatus.PENDING)
        self.assertEqual(event.formatted_price, "59 USD")
        self.assertEqual(event.guest_access_code, "AMOUR2026")
        self.assertEqual(event.location, "")
        self.assertEqual(event.media_retention_days, 7)
        self.assertTrue(event.public_access_key)
        self.assertFalse(event.qr_code_image)

    def test_event_form_is_french_and_event_agnostic(self):
        self.client.login(username="owner", password="secret")

        response = self.client.get(reverse("events:create"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Créer un événement")
        self.assertContains(response, "Nom affiché aux invités")
        self.assertContains(response, "Type d&#x27;événement personnalisé")
        self.assertContains(response, "Accès invité")
        self.assertContains(response, "Sécurité après le scan")
        self.assertContains(response, "data-custom-event-type-field")
        self.assertContains(response, "data-custom-event-type-field hidden")
        self.assertContains(response, "data-moment-select")
        self.assertContains(response, "moment-suggestions-data")
        self.assertContains(response, "event-form")
        self.assertNotContains(response, "Collecte active")
        self.assertNotContains(response, "Lieu (optionnel)")
        self.assertNotContains(response, "Conservation des médias")
        self.assertNotContains(response, "Couple name")

    def test_organizer_can_choose_and_add_event_moments(self):
        ceremony = MomentTemplate.objects.get(code="ceremony")
        self.client.login(username="owner", password="secret")

        response = self.client.post(
            reverse("events:create"),
            {
                "title": "Mariage moments choisis",
                "couple_name": "Lea & Sam",
                "event_type": self.event_type.pk,
                "moments": [str(ceremony.pk), "new:After party"],
                "event_date": "2026-07-08",
                "location": "",
                "welcome_message": "Partagez vos plus beaux souvenirs.",
                "guest_access_code": "",
                "is_active": "on",
            },
        )

        event = Event.objects.get(title="Mariage moments choisis")
        self.assertRedirects(response, reverse("events:detail", kwargs={"pk": event.pk}))
        self.assertEqual(
            list(event.upload_categories.filter(is_active=True).order_by("sort_order").values_list("code", flat=True)),
            ["ceremony", "after-party"],
        )
        custom_moment = MomentTemplate.objects.get(code="after-party")
        self.assertEqual(custom_moment.label, "After party")
        self.assertEqual(custom_moment.status, MomentTemplate.ModerationStatus.PENDING)
        self.assertEqual(custom_moment.usage_count, 1)
        self.assertEqual(custom_moment.created_by, self.user)

    def test_custom_event_type_is_created_when_other_is_selected(self):
        other_type = EventType.objects.get(code="other")
        self.client.login(username="owner", password="secret")

        response = self.client.post(
            reverse("events:create"),
            {
                "title": "Baby shower de Lina",
                "couple_name": "Baby shower de Lina",
                "event_type": other_type.pk,
                "custom_event_type_label": "Baby shower",
                "event_date": "2026-07-08",
                "location": "",
                "welcome_message": "Partagez vos plus beaux souvenirs.",
                "guest_access_code": "",
                "is_active": "on",
                "media_retention_days": "7",
            },
        )

        event = Event.objects.get(title="Baby shower de Lina")
        self.assertRedirects(response, reverse("events:detail", kwargs={"pk": event.pk}))
        self.assertEqual(event.event_type.label, "Baby shower")
        self.assertEqual(event.event_type.code, "baby-shower")

    def test_other_event_type_requires_custom_label(self):
        other_type = EventType.objects.get(code="other")
        self.client.login(username="owner", password="secret")

        response = self.client.post(
            reverse("events:create"),
            {
                "title": "Evenement mystere",
                "couple_name": "",
                "event_type": other_type.pk,
                "custom_event_type_label": "",
                "event_date": "2026-07-08",
                "location": "",
                "welcome_message": "",
                "guest_access_code": "",
                "is_active": "on",
                "media_retention_days": "7",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Indiquez le type d&#x27;événement")
        self.assertFalse(Event.objects.filter(title="Evenement mystere").exists())

    def test_event_cover_image_is_compressed_before_storage(self):
        self.client.login(username="owner", password="secret")
        image_buffer = BytesIO()
        Image.new("RGB", (2400, 1600), (180, 92, 104)).save(image_buffer, format="PNG")
        image_buffer.seek(0)
        cover_image = SimpleUploadedFile(
            "cover.png",
            image_buffer.read(),
            content_type="image/png",
        )

        response = self.client.post(
            reverse("events:create"),
            {
                "title": "Mariage couverture",
                "couple_name": "Lea & Sam",
                "event_type": self.event_type.pk,
                "event_date": "2026-07-08",
                "location": "Paris",
                "welcome_message": "Partagez vos plus beaux souvenirs.",
                "guest_access_code": "",
                "is_active": "on",
                "cover_image": cover_image,
            },
        )

        event = Event.objects.get(title="Mariage couverture")
        self.assertRedirects(response, reverse("events:detail", kwargs={"pk": event.pk}))
        self.assertTrue(event.cover_image.name.endswith(".jpg"))
        with Image.open(event.cover_image) as saved_image:
            self.assertEqual(saved_image.format, "JPEG")
            self.assertLessEqual(saved_image.width, 1800)
            self.assertLessEqual(saved_image.height, 1200)

    @patch("django.db.models.fields.files.FieldFile.save", side_effect=OSError("storage down"))
    def test_event_cover_storage_error_returns_form_error(self, _field_file_save):
        self.client.login(username="owner", password="secret")
        image_buffer = BytesIO()
        Image.new("RGB", (24, 24), (180, 92, 104)).save(image_buffer, format="JPEG")
        image_buffer.seek(0)
        cover_image = SimpleUploadedFile(
            "cover.jpg",
            image_buffer.read(),
            content_type="image/jpeg",
        )

        response = self.client.post(
            reverse("events:create"),
            {
                "title": "Mariage stockage indisponible",
                "couple_name": "Lea & Sam",
                "event_type": self.event_type.pk,
                "event_date": "2026-07-08",
                "location": "Paris",
                "welcome_message": "Partagez vos plus beaux souvenirs.",
                "guest_access_code": "",
                "is_active": "on",
                "cover_image": cover_image,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, STORAGE_UNAVAILABLE_MESSAGE)
        self.assertFalse(Event.objects.filter(title="Mariage stockage indisponible").exists())

    @override_settings(MEMORA_MAX_COVER_IMAGE_SIZE=4)
    def test_event_cover_image_rejects_too_large_file(self):
        self.client.login(username="owner", password="secret")
        image_buffer = BytesIO()
        Image.new("RGB", (24, 24), (180, 92, 104)).save(image_buffer, format="JPEG")
        image_buffer.seek(0)
        cover_image = SimpleUploadedFile(
            "cover.jpg",
            image_buffer.read(),
            content_type="image/jpeg",
        )

        response = self.client.post(
            reverse("events:create"),
            {
                "title": "Mariage image lourde",
                "couple_name": "Lea & Sam",
                "event_type": self.event_type.pk,
                "event_date": "2026-07-08",
                "location": "Paris",
                "welcome_message": "Partagez vos plus beaux souvenirs.",
                "guest_access_code": "",
                "is_active": "on",
                "cover_image": cover_image,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Cette image est trop lourde.", str(response.context["form"].errors))
        self.assertFalse(Event.objects.filter(title="Mariage image lourde").exists())

    def test_event_detail_is_limited_to_owner(self):
        event = Event.objects.create(
            organizer=self.other_user,
            title="Evenement prive",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
        )
        self.client.login(username="owner", password="secret")

        response = self.client.get(reverse("events:detail", kwargs={"pk": event.pk}))

        self.assertEqual(response.status_code, 404)

    def test_event_detail_displays_dynamic_private_qr_code(self):
        event = Event.objects.create(
            organizer=self.user,
            title="Reception QR prive",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
        )
        self.assertFalse(event.qr_code_image)
        self.client.login(username="owner", password="secret")

        response = self.client.get(reverse("events:detail", kwargs={"pk": event.pk}))

        event.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(event.qr_code_image)
        self.assertContains(response, reverse("events:qr_code", kwargs={"pk": event.pk}))

    def test_owner_can_download_dynamic_qr_code(self):
        event = Event.objects.create(
            organizer=self.user,
            title="Reception QR dynamique",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
        )
        self.client.login(username="owner", password="secret")

        response = self.client.get(reverse("events:qr_code", kwargs={"pk": event.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertGreater(len(response.content), 1000)

    def test_public_event_page_uses_slug(self):
        event = Event.objects.create(
            organizer=self.user,
            title="Reception Memora",
            couple_name="Lea & Sam",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
            welcome_message="Bienvenue dans nos souvenirs.",
        )
        self.mark_paid(event)

        response = self.client.get(event.get_public_url(), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Lea &amp; Sam")
        self.assertContains(response, "Bienvenue dans nos souvenirs.")

    def test_public_event_redirects_straight_to_upload_form(self):
        event = Event.objects.create(
            organizer=self.user,
            title="Reception directe",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
        )
        self.mark_paid(event)

        response = self.client.get(event.get_public_url())

        self.assertRedirects(response, reverse("uploads:create", kwargs={"slug": event.slug, "access_key": event.public_access_key}))

    def test_public_event_with_guest_access_code_requires_session_validation(self):
        event = Event.objects.create(
            organizer=self.user,
            title="Reception code",
            couple_name="Lea & Sam",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
            guest_access_code="AMOUR2026",
        )
        self.mark_paid(event)

        response = self.client.get(event.get_public_url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Entrez le code invité.")
        self.assertNotContains(response, "Ajouter un souvenir")

        wrong_response = self.client.post(event.get_public_url(), {"guest_access_code": "NON"})
        self.assertEqual(wrong_response.status_code, 200)
        self.assertContains(wrong_response, "Code incorrect.")

        valid_response = self.client.post(event.get_public_url(), {"guest_access_code": "amour2026"})
        self.assertRedirects(valid_response, event.get_public_url(), target_status_code=302)

        unlocked_response = self.client.get(event.get_public_url())
        self.assertRedirects(
            unlocked_response,
            reverse("uploads:create", kwargs={"slug": event.slug, "access_key": event.public_access_key}),
        )

    @override_settings(MEMORA_GUEST_ACCESS_ATTEMPT_LIMIT=2, MEMORA_GUEST_ACCESS_LOCKOUT_SECONDS=60)
    def test_public_event_guest_access_code_is_throttled(self):
        cache.clear()
        event = Event.objects.create(
            organizer=self.user,
            title="Reception code throttle",
            couple_name="Lea & Sam",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
            guest_access_code="AMOUR2026",
        )
        self.mark_paid(event)

        first_response = self.client.post(event.get_public_url(), {"guest_access_code": "NON"})
        self.assertContains(first_response, "Code incorrect.")

        second_response = self.client.post(event.get_public_url(), {"guest_access_code": "FAUX"})
        self.assertContains(second_response, "Trop de tentatives.")

        locked_response = self.client.post(event.get_public_url(), {"guest_access_code": "amour2026"})
        self.assertEqual(locked_response.status_code, 200)
        self.assertContains(locked_response, "Trop de tentatives.")
        self.assertNotContains(locked_response, "Ajouter un souvenir")

    def test_public_event_requires_access_key(self):
        event = Event.objects.create(
            organizer=self.user,
            title="Reception privee",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
        )

        response_without_key = self.client.get(f"/e/{event.slug}/")
        response_with_wrong_key = self.client.get(
            reverse(
                "public_event",
                kwargs={"slug": event.slug, "access_key": "mauvaise-cle"},
            )
        )

        self.assertEqual(response_without_key.status_code, 404)
        self.assertEqual(response_with_wrong_key.status_code, 404)

    def test_public_event_requires_payment_activation(self):
        event = Event.objects.create(
            organizer=self.user,
            title="Reception non payee",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
        )

        response = self.client.get(event.get_public_url())

        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "Événement pas encore activé", status_code=403)

    def test_public_event_displays_closed_message_after_collection_is_closed(self):
        event = Event.objects.create(
            organizer=self.user,
            title="Reception cloturee",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
            payment_status=Event.PaymentStatus.PAID,
            is_active=False,
        )

        response = self.client.get(event.get_public_url())

        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "Événement clôturé", status_code=403)
        self.assertContains(response, "La collecte des souvenirs est terminée", status_code=403)

    def test_event_detail_displays_media_dashboard(self):
        event = Event.objects.create(
            organizer=self.user,
            title="Reception Dashboard",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
            guest_access_code="AMOUR2026",
        )
        ceremony = event.upload_categories.get(code="ceremony")
        dancefloor = event.upload_categories.get(code="dancefloor")
        GuestUpload.objects.create(
            event=event,
            category=ceremony,
            media_file="events/reception-dashboard/uploads/ceremony/photo.jpg",
            media_type=GuestUpload.MediaType.IMAGE,
            original_filename="photo.jpg",
            file_size=123,
            moderation_status=GuestUpload.ModerationStatus.APPROVED,
        )
        GuestUpload.objects.create(
            event=event,
            category=dancefloor,
            media_file="events/reception-dashboard/uploads/dancefloor/video.mp4",
            media_type=GuestUpload.MediaType.VIDEO,
            original_filename="video.mp4",
            file_size=456,
            moderation_status=GuestUpload.ModerationStatus.APPROVED,
            is_selected_for_movie=True,
        )
        GuestUpload.objects.create(
            event=event,
            category=dancefloor,
            media_file="events/reception-dashboard/uploads/dancefloor/deleted.jpg",
            media_type=GuestUpload.MediaType.IMAGE,
            original_filename="deleted.jpg",
            file_size=789,
            is_deleted=True,
        )
        self.client.login(username="owner", password="secret")

        response = self.client.get(reverse("events:detail", kwargs={"pk": event.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Dashboard organisateur")
        self.assertContains(response, "Accès invité")
        self.assertContains(response, "Suivi en direct")
        self.assertContains(response, "Collecte active")
        self.assertContains(response, "QR code invité")
        self.assertContains(response, "Paramètres essentiels")
        self.assertContains(response, "Code AMOUR2026")
        self.assertContains(response, "AMOUR2026")
        self.assertContains(response, event.public_access_key)
        self.assertContains(response, "Médias invités")
        self.assertContains(response, "Derniers souvenirs")
        self.assertContains(response, "photo.jpg")
        self.assertContains(response, "video.mp4")
        self.assertNotContains(response, "deleted.jpg")
        self.assertEqual(response.context["media_stats"]["total"], 2)
        self.assertEqual(response.context["media_stats"]["photos"], 1)
        self.assertEqual(response.context["media_stats"]["videos"], 1)
        self.assertEqual(response.context["media_stats"]["selected_for_movie"], 1)

    def test_event_detail_shows_hourly_breakdown_instead_of_category(self):
        # Depuis que les invites ne choisissent plus de moment, la repartition
        # par categorie n'aurait plus de sens (tout tomberait dans "Autre").
        event = Event.objects.create(
            organizer=self.user,
            title="Reception Horaire",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
        )
        self.mark_paid(event)
        category = event.upload_categories.get(code="ceremony")
        first = GuestUpload.objects.create(
            event=event,
            category=category,
            media_file="events/reception-horaire/uploads/ceremony/a.jpg",
            media_type=GuestUpload.MediaType.IMAGE,
            original_filename="a.jpg",
            file_size=1,
            moderation_status=GuestUpload.ModerationStatus.APPROVED,
        )
        second = GuestUpload.objects.create(
            event=event,
            category=category,
            media_file="events/reception-horaire/uploads/ceremony/b.jpg",
            media_type=GuestUpload.MediaType.IMAGE,
            original_filename="b.jpg",
            file_size=1,
            moderation_status=GuestUpload.ModerationStatus.APPROVED,
        )
        # auto_now_add ignore toute valeur passee a la creation : on la fixe apres coup.
        GuestUpload.objects.filter(pk=first.pk).update(
            uploaded_at=timezone.make_aware(datetime(2026, 7, 8, 19, 0))
        )
        GuestUpload.objects.filter(pk=second.pk).update(
            uploaded_at=timezone.make_aware(datetime(2026, 7, 8, 20, 0))
        )
        self.client.login(username="owner", password="secret")

        response = self.client.get(reverse("events:detail", kwargs={"pk": event.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Souvenirs par heure")
        self.assertNotContains(response, "Répartition par moment")
        breakdown = response.context["hourly_breakdown"]
        self.assertEqual([row["count"] for row in breakdown], [1, 1])

    def test_event_detail_shows_readiness_checklist(self):
        incomplete_event = Event.objects.create(
            organizer=self.user,
            title="Reception Incomplete",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
        )
        self.client.login(username="owner", password="secret")

        response = self.client.get(reverse("events:detail", kwargs={"pk": incomplete_event.pk}))

        self.assertContains(response, "Il reste des étapes")
        self.assertFalse(response.context["readiness_checklist"]["is_ready"])
        self.assertContains(response, "Paiement validé")

        complete_event = Event.objects.create(
            organizer=self.user,
            title="Reception Complete",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
            welcome_message="Bienvenue !",
        )
        self.mark_paid(complete_event)

        response = self.client.get(reverse("events:detail", kwargs={"pk": complete_event.pk}))

        self.assertContains(response, "Prêt pour la collecte")
        self.assertTrue(response.context["readiness_checklist"]["is_ready"])

    def test_live_stats_panel_reflects_current_counts(self):
        event = Event.objects.create(
            organizer=self.user,
            title="Reception Live",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
        )
        self.mark_paid(event)
        category = event.upload_categories.get(code="ceremony")
        GuestUpload.objects.create(
            event=event,
            category=category,
            media_file="events/reception-live/uploads/ceremony/a.jpg",
            media_type=GuestUpload.MediaType.IMAGE,
            original_filename="a.jpg",
            file_size=1,
            moderation_status=GuestUpload.ModerationStatus.APPROVED,
        )
        self.client.login(username="owner", password="secret")

        response = self.client.get(reverse("events:live_stats", kwargs={"pk": event.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-live-stats-panel")
        self.assertContains(response, 'data-active="1"')
        self.assertEqual(response.context["media_stats"]["total"], 1)

    def test_live_stats_panel_is_limited_to_owner(self):
        event = Event.objects.create(
            organizer=self.other_user,
            title="Reception Autrui",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
        )
        self.client.login(username="owner", password="secret")

        response = self.client.get(reverse("events:live_stats", kwargs={"pk": event.pk}))

        self.assertEqual(response.status_code, 404)

    def test_event_detail_displays_latest_generated_movie(self):
        event = Event.objects.create(
            organizer=self.user,
            title="Reception Film",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
        )
        GeneratedMovie.objects.create(
            event=event,
            status=GeneratedMovie.Status.COMPLETED,
            final_file="events/reception-film/movies/memora_reception_film.mp4",
        )
        self.client.login(username="owner", password="secret")

        response = self.client.get(reverse("events:detail", kwargs={"pk": event.pk}))

        self.assertContains(response, "Vidéo automatique")
        self.assertContains(response, "Ouvrir le film")
        self.assertContains(response, reverse("events:movie_ready", kwargs={"pk": event.pk}))
        self.assertContains(response, "100%")

    def test_owner_can_view_ready_movie_page(self):
        event = Event.objects.create(
            organizer=self.user,
            title="Reception Film Pret",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
            couple_name="Camille & Noe",
        )
        GeneratedMovie.objects.create(
            event=event,
            status=GeneratedMovie.Status.COMPLETED,
            final_file="events/reception-film/movies/memora_reception_film.mp4",
        )
        self.client.login(username="owner", password="secret")

        response = self.client.get(reverse("events:movie_ready", kwargs={"pk": event.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Votre film est prêt")
        self.assertContains(response, "Camille &amp; Noe")
        self.assertContains(response, "Télécharger le film")
        self.assertContains(response, "Lien de partage")
        self.assertContains(response, event.public_access_key)
        self.assertContains(response, reverse("events:download_movie", kwargs={"pk": event.pk}))

    def test_owner_movie_page_shows_pending_state_when_movie_is_not_ready(self):
        event = Event.objects.create(
            organizer=self.user,
            title="Reception Film En Cours",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
        )
        GeneratedMovie.objects.create(
            event=event,
            status=GeneratedMovie.Status.PROCESSING,
            progress_percent=42,
            progress_message="Sélection des meilleurs souvenirs.",
        )
        self.client.login(username="owner", password="secret")

        response = self.client.get(reverse("events:movie_ready", kwargs={"pk": event.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Film en préparation")
        # A la decimale pres (locale fr : virgule) depuis que progress_percent
        # bouge vraiment pendant le rendu Remotion, plutot qu'un entier fige.
        self.assertContains(response, "42,0%")
        self.assertContains(response, "Sélection des meilleurs souvenirs.")

    def test_other_organizer_cannot_view_ready_movie_page(self):
        event = Event.objects.create(
            organizer=self.other_user,
            title="Reception Film Prive",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
        )
        GeneratedMovie.objects.create(
            event=event,
            status=GeneratedMovie.Status.COMPLETED,
            final_file="events/reception-film/movies/private.mp4",
        )
        self.client.login(username="owner", password="secret")

        response = self.client.get(reverse("events:movie_ready", kwargs={"pk": event.pk}))

        self.assertEqual(response.status_code, 404)

    def test_public_movie_share_displays_completed_movie_without_login(self):
        event = Event.objects.create(
            organizer=self.user,
            title="Reception Film Partage",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
        )
        self.mark_paid(event)
        GeneratedMovie.objects.create(
            event=event,
            status=GeneratedMovie.Status.COMPLETED,
            final_file="events/reception-film/movies/shared.mp4",
        )

        response = self.client.get(
            reverse(
                "public_movie",
                kwargs={"slug": event.slug, "access_key": event.public_access_key},
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Film prêt")
        self.assertContains(response, "Télécharger le film")
        self.assertNotContains(response, "Retour dashboard")

    def test_public_movie_share_hides_unfinished_movie(self):
        event = Event.objects.create(
            organizer=self.user,
            title="Reception Film Non Pret",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
        )
        GeneratedMovie.objects.create(event=event, status=GeneratedMovie.Status.PROCESSING)

        response = self.client.get(
            reverse(
                "public_movie",
                kwargs={"slug": event.slug, "access_key": event.public_access_key},
            )
        )

        self.assertEqual(response.status_code, 404)

    def test_owner_can_download_ready_movie(self):
        event = Event.objects.create(
            organizer=self.user,
            title="Reception Film Download",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
            couple_name="Camille & Noe",
        )
        movie_name = "events/reception-film/movies/download.mp4"
        movie_path = Path(TEST_MEDIA_ROOT) / movie_name
        movie_path.parent.mkdir(parents=True, exist_ok=True)
        movie_path.write_bytes(b"movie-bytes")
        GeneratedMovie.objects.create(
            event=event,
            status=GeneratedMovie.Status.COMPLETED,
            final_file=movie_name,
        )
        self.client.login(username="owner", password="secret")

        response = self.client.get(reverse("events:download_movie", kwargs={"pk": event.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Disposition"], 'attachment; filename="memora-camille-noe.mp4"')
        self.assertEqual(b"".join(response.streaming_content), b"movie-bytes")

    def test_owner_can_download_the_teaser_variant_and_unknown_variants_fall_back_to_the_film(self):
        event = Event.objects.create(
            organizer=self.user,
            title="Reception Film Variantes",
            couple_name="Camille & Noe",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
        )
        for name, content in (("film.mp4", b"film-bytes"), ("teaser.mp4", b"teaser-bytes")):
            path = Path(TEST_MEDIA_ROOT) / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        GeneratedMovie.objects.create(
            event=event,
            status=GeneratedMovie.Status.COMPLETED,
            final_file="film.mp4",
            teaser_file="teaser.mp4",
        )
        self.client.login(username="owner", password="secret")
        url = reverse("events:download_movie", kwargs={"pk": event.pk})

        teaser = self.client.get(url, {"v": "teaser"})
        unknown = self.client.get(url, {"v": "inconnu"})

        self.assertEqual(b"".join(teaser.streaming_content), b"teaser-bytes")
        self.assertIn("teaser", teaser["Content-Disposition"])
        self.assertEqual(b"".join(unknown.streaming_content), b"film-bytes")

    def test_event_detail_displays_automatic_movie_schedule(self):
        event = Event.objects.create(
            organizer=self.user,
            title="Reception Film Programme",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
        )
        self.client.login(username="owner", password="secret")

        response = self.client.get(reverse("events:detail", kwargs={"pk": event.pk}))

        self.assertContains(response, "Génération automatique prévue le 09/07/2026 à 12:00")
        self.assertContains(response, "horaire automatique")

    def test_owner_can_poll_movie_status_panel(self):
        event = Event.objects.create(
            organizer=self.user,
            title="Reception Film Statut",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
        )
        GeneratedMovie.objects.create(
            event=event,
            status=GeneratedMovie.Status.PROCESSING,
            progress_percent=68,
            progress_message="Assemblage des clips sélectionnés.",
        )
        self.client.login(username="owner", password="secret")

        response = self.client.get(reverse("events:movie_status", kwargs={"pk": event.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "68,0%")
        self.assertContains(response, "Assemblage des clips sélectionnés.")

    def test_guestbook_page_shows_montage_progress_while_processing(self):
        from guestbook.models import GuestBookMovie

        event = Event.objects.create(
            organizer=self.user,
            title="Reception Livre Or En Cours",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
        )
        GuestBookMovie.objects.create(
            event=event,
            status=GuestBookMovie.Status.PROCESSING,
            progress_percent=37,
            progress_message="Montage du livre d'or en cours.",
        )
        self.client.login(username="owner", password="secret")

        response = self.client.get(reverse("events:guestbook_messages", kwargs={"pk": event.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "37,0%")
        # Apostrophe echappee en HTML (d&#x27;or) : on verifie le texte autour.
        self.assertContains(response, "Montage du livre d")
        self.assertContains(response, "or en cours.")
        self.assertContains(response, reverse("events:guestbook_movie_status", kwargs={"pk": event.pk}))

    def test_owner_can_poll_guestbook_movie_status_panel(self):
        from guestbook.models import GuestBookMovie

        event = Event.objects.create(
            organizer=self.user,
            title="Reception Livre Or Statut",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
        )
        GuestBookMovie.objects.create(
            event=event,
            status=GuestBookMovie.Status.PROCESSING,
            progress_percent=52,
            progress_message="Montage du livre d'or en cours.",
        )
        self.client.login(username="owner", password="secret")

        response = self.client.get(reverse("events:guestbook_movie_status", kwargs={"pk": event.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "52,0%")
        # Apostrophe echappee en HTML (d&#x27;or) : on verifie le texte autour.
        self.assertContains(response, "Montage du livre d")
        self.assertContains(response, "or en cours.")

    def test_other_organizer_cannot_poll_guestbook_movie_status_panel(self):
        from guestbook.models import GuestBookMovie

        event = Event.objects.create(
            organizer=self.other_user,
            title="Reception Livre Or Privee",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
        )
        GuestBookMovie.objects.create(event=event, status=GuestBookMovie.Status.PROCESSING)
        self.client.login(username="owner", password="secret")

        response = self.client.get(reverse("events:guestbook_movie_status", kwargs={"pk": event.pk}))

        self.assertEqual(response.status_code, 404)

    @patch("events.views.create_event_movie_job")
    def test_owner_can_generate_event_movie(self, create_event_movie_job):
        event = Event.objects.create(
            organizer=self.user,
            title="Reception Film Auto",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
        )
        self.mark_paid(event)
        create_event_movie_job.return_value = GeneratedMovie.objects.create(event=event)
        self.client.login(username="owner", password="secret")

        response = self.client.post(reverse("events:generate_movie", kwargs={"pk": event.pk}))

        self.assertRedirects(response, reverse("events:detail", kwargs={"pk": event.pk}))
        create_event_movie_job.assert_called_once_with(event, allow_retry=True)

    @patch("events.views.create_event_movie_job")
    def test_owner_cannot_generate_movie_before_payment_activation(self, create_event_movie_job):
        event = Event.objects.create(
            organizer=self.user,
            title="Reception Film Non Paye",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
        )
        self.client.login(username="owner", password="secret")

        response = self.client.post(reverse("events:generate_movie", kwargs={"pk": event.pk}))

        self.assertRedirects(response, reverse("events:detail", kwargs={"pk": event.pk}))
        create_event_movie_job.assert_not_called()

    def test_movie_status_panel_hides_technical_errors(self):
        event = Event.objects.create(
            organizer=self.user,
            title="Reception Film Erreur",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
        )
        GeneratedMovie.objects.create(
            event=event,
            status=GeneratedMovie.Status.FAILED,
            progress_message="La generation a ete interrompue. Vous pouvez relancer le film.",
            error_logs="An error occurred (403) when calling the HeadObject operation: Forbidden",
        )
        self.client.login(username="owner", password="secret")

        response = self.client.get(reverse("events:movie_status", kwargs={"pk": event.pk}))

        self.assertContains(response, "Vous pouvez relancer le film")
        self.assertContains(response, "détails techniques restent gérés en interne")
        self.assertNotContains(response, "HeadObject")

    @patch("events.views.create_event_movie_job")
    def test_other_organizer_cannot_generate_event_movie(self, create_event_movie_job):
        event = Event.objects.create(
            organizer=self.other_user,
            title="Reception Film Prive",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
        )
        self.client.login(username="owner", password="secret")

        response = self.client.post(reverse("events:generate_movie", kwargs={"pk": event.pk}))

        self.assertEqual(response.status_code, 404)
        create_event_movie_job.assert_not_called()

    def test_event_detail_links_to_full_media_library(self):
        event = Event.objects.create(
            organizer=self.user,
            title="Reception Bibliotheque",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
        )
        self.client.login(username="owner", password="secret")

        response = self.client.get(reverse("events:detail", kwargs={"pk": event.pk}))

        self.assertContains(response, reverse("events:media_list", kwargs={"pk": event.pk}))
        self.assertContains(response, "Voir tous les médias")

    def test_owner_can_browse_and_filter_event_media(self):
        event = Event.objects.create(
            organizer=self.user,
            title="Reception Medias",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
        )
        ceremony = event.upload_categories.get(code="ceremony")
        dancefloor = event.upload_categories.get(code="dancefloor")
        GuestUpload.objects.create(
            event=event,
            category=ceremony,
            media_file="events/reception-medias/uploads/ceremony/photo.jpg",
            media_type=GuestUpload.MediaType.IMAGE,
            original_filename="photo.jpg",
            file_size=123,
            moderation_status=GuestUpload.ModerationStatus.APPROVED,
        )
        GuestUpload.objects.create(
            event=event,
            category=dancefloor,
            media_file="events/reception-medias/uploads/dancefloor/video.mp4",
            media_type=GuestUpload.MediaType.VIDEO,
            original_filename="video.mp4",
            file_size=456,
            moderation_status=GuestUpload.ModerationStatus.APPROVED,
            is_selected_for_movie=True,
        )
        GuestUpload.objects.create(
            event=event,
            category=dancefloor,
            media_file="events/reception-medias/uploads/dancefloor/deleted.jpg",
            media_type=GuestUpload.MediaType.IMAGE,
            original_filename="deleted.jpg",
            file_size=789,
            is_deleted=True,
        )
        GuestUpload.objects.create(
            event=event,
            category=dancefloor,
            media_file="events/reception-medias/uploads/dancefloor/rejected.jpg",
            media_type=GuestUpload.MediaType.IMAGE,
            original_filename="rejected.jpg",
            file_size=321,
            moderation_status=GuestUpload.ModerationStatus.REJECTED,
        )
        self.client.login(username="owner", password="secret")

        response = self.client.get(reverse("events:media_list", kwargs={"pk": event.pk}))
        filtered_response = self.client.get(
            reverse("events:media_list", kwargs={"pk": event.pk}),
            {"category": "dancefloor", "type": GuestUpload.MediaType.VIDEO},
        )
        selected_response = self.client.get(
            reverse("events:media_list", kwargs={"pk": event.pk}),
            {"movie": "selected"},
        )
        rejected_response = self.client.get(
            reverse("events:media_list", kwargs={"pk": event.pk}),
            {"status": GuestUpload.ModerationStatus.REJECTED},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Photos et videos envoyees par les invites.")
        self.assertContains(response, "1 media selectionne pour le film souvenir.")
        self.assertContains(response, "photo.jpg")
        self.assertContains(response, "video.mp4")
        self.assertContains(response, "Retirer du film")
        self.assertContains(response, "Garder pour le film")
        self.assertContains(response, "Accepte")
        self.assertNotContains(response, "deleted.jpg")
        self.assertNotContains(response, "rejected.jpg")
        self.assertEqual(
            list(response.context["uploads"]),
            list(
                event.guest_uploads.filter(is_deleted=False)
                .exclude(moderation_status=GuestUpload.ModerationStatus.REJECTED)
                .order_by("-uploaded_at", "-pk")
            ),
        )
        self.assertContains(filtered_response, "video.mp4")
        self.assertNotContains(filtered_response, "photo.jpg")
        self.assertEqual(filtered_response.context["selected_category"], "dancefloor")
        self.assertEqual(filtered_response.context["selected_media_type"], GuestUpload.MediaType.VIDEO)
        self.assertContains(selected_response, "video.mp4")
        self.assertNotContains(selected_response, "photo.jpg")
        self.assertEqual(selected_response.context["selected_movie_filter"], "selected")
        self.assertContains(rejected_response, "rejected.jpg")
        self.assertNotContains(rejected_response, "photo.jpg")
        self.assertEqual(rejected_response.context["selected_moderation_status"], GuestUpload.ModerationStatus.REJECTED)

    def test_owner_can_toggle_media_movie_selection(self):
        event = Event.objects.create(
            organizer=self.user,
            title="Reception Selection",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
        )
        ceremony = event.upload_categories.get(code="ceremony")
        upload = GuestUpload.objects.create(
            event=event,
            category=ceremony,
            media_file="events/reception-selection/uploads/ceremony/photo.jpg",
            media_type=GuestUpload.MediaType.IMAGE,
            original_filename="photo.jpg",
            file_size=123,
            moderation_status=GuestUpload.ModerationStatus.APPROVED,
        )
        self.client.login(username="owner", password="secret")

        response = self.client.post(
            reverse("events:toggle_movie_selection", kwargs={"pk": event.pk, "upload_pk": upload.pk}),
            {"next": reverse("events:media_list", kwargs={"pk": event.pk})},
        )
        upload.refresh_from_db()

        self.assertRedirects(response, reverse("events:media_list", kwargs={"pk": event.pk}))
        self.assertTrue(upload.is_selected_for_movie)

        self.client.post(reverse("events:toggle_movie_selection", kwargs={"pk": event.pk, "upload_pk": upload.pk}))
        upload.refresh_from_db()
        self.assertFalse(upload.is_selected_for_movie)

    def test_owner_can_moderate_event_media(self):
        event = Event.objects.create(
            organizer=self.user,
            title="Reception Moderation",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
        )
        ceremony = event.upload_categories.get(code="ceremony")
        upload = GuestUpload.objects.create(
            event=event,
            category=ceremony,
            media_file="events/reception-moderation/uploads/ceremony/photo.jpg",
            media_type=GuestUpload.MediaType.IMAGE,
            original_filename="photo.jpg",
            file_size=123,
        )
        self.client.login(username="owner", password="secret")

        upload.is_selected_for_movie = True
        upload.save(update_fields=["is_selected_for_movie"])
        reject_response = self.client.post(
            reverse("events:set_media_moderation", kwargs={"pk": event.pk, "upload_pk": upload.pk}),
            {
                "status": GuestUpload.ModerationStatus.REJECTED,
                "next": reverse("events:media_list", kwargs={"pk": event.pk}),
            },
        )
        upload.refresh_from_db()

        self.assertRedirects(reject_response, reverse("events:media_list", kwargs={"pk": event.pk}))
        self.assertEqual(upload.moderation_status, GuestUpload.ModerationStatus.REJECTED)
        self.assertFalse(upload.is_selected_for_movie)

        restore_response = self.client.post(
            reverse("events:set_media_moderation", kwargs={"pk": event.pk, "upload_pk": upload.pk}),
            {"status": GuestUpload.ModerationStatus.APPROVED},
        )
        upload.refresh_from_db()

        self.assertRedirects(restore_response, reverse("events:media_list", kwargs={"pk": event.pk}))
        self.assertEqual(upload.moderation_status, GuestUpload.ModerationStatus.APPROVED)

    def test_other_organizer_cannot_browse_event_media(self):
        event = Event.objects.create(
            organizer=self.other_user,
            title="Reception Media Privee",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
        )
        self.client.login(username="owner", password="secret")

        response = self.client.get(reverse("events:media_list", kwargs={"pk": event.pk}))

        self.assertEqual(response.status_code, 404)

    def test_other_organizer_cannot_toggle_media_movie_selection(self):
        event = Event.objects.create(
            organizer=self.other_user,
            title="Reception Selection Privee",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
        )
        ceremony = event.upload_categories.get(code="ceremony")
        upload = GuestUpload.objects.create(
            event=event,
            category=ceremony,
            media_file="events/reception-selection-privee/uploads/ceremony/photo.jpg",
            media_type=GuestUpload.MediaType.IMAGE,
            original_filename="photo.jpg",
            file_size=123,
        )
        self.client.login(username="owner", password="secret")

        response = self.client.post(
            reverse("events:toggle_movie_selection", kwargs={"pk": event.pk, "upload_pk": upload.pk})
        )
        upload.refresh_from_db()

        self.assertEqual(response.status_code, 404)
        self.assertFalse(upload.is_selected_for_movie)

    def test_other_organizer_cannot_moderate_event_media(self):
        event = Event.objects.create(
            organizer=self.other_user,
            title="Reception Moderation Privee",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
        )
        ceremony = event.upload_categories.get(code="ceremony")
        upload = GuestUpload.objects.create(
            event=event,
            category=ceremony,
            media_file="events/reception-moderation-privee/uploads/ceremony/photo.jpg",
            media_type=GuestUpload.MediaType.IMAGE,
            original_filename="photo.jpg",
            file_size=123,
        )
        self.client.login(username="owner", password="secret")

        response = self.client.post(
            reverse("events:set_media_moderation", kwargs={"pk": event.pk, "upload_pk": upload.pk}),
            {"status": GuestUpload.ModerationStatus.APPROVED},
        )
        upload.refresh_from_db()

        self.assertEqual(response.status_code, 404)
        self.assertEqual(upload.moderation_status, GuestUpload.ModerationStatus.APPROVED)

    def test_owner_can_download_event_zip(self):
        event = Event.objects.create(
            organizer=self.user,
            title="Reception Zip",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
        )
        ceremony = event.upload_categories.get(code="ceremony")
        dancefloor = event.upload_categories.get(code="dancefloor")
        GuestUpload.objects.create(
            event=event,
            category=ceremony,
            media_file=SimpleUploadedFile("photo.jpg", b"image-bytes", content_type="image/jpeg"),
            media_type=GuestUpload.MediaType.IMAGE,
            original_filename="photo.jpg",
            file_size=11,
            moderation_status=GuestUpload.ModerationStatus.APPROVED,
        )
        GuestUpload.objects.create(
            event=event,
            category=dancefloor,
            media_file=SimpleUploadedFile("video.mp4", b"video-bytes", content_type="video/mp4"),
            media_type=GuestUpload.MediaType.VIDEO,
            original_filename="video.mp4",
            file_size=11,
            moderation_status=GuestUpload.ModerationStatus.APPROVED,
        )
        GuestUpload.objects.create(
            event=event,
            category=dancefloor,
            media_file=SimpleUploadedFile("deleted.jpg", b"deleted", content_type="image/jpeg"),
            media_type=GuestUpload.MediaType.IMAGE,
            original_filename="deleted.jpg",
            file_size=7,
            is_deleted=True,
        )
        GuestUpload.objects.create(
            event=event,
            category=dancefloor,
            media_file=SimpleUploadedFile("rejected.jpg", b"rejected", content_type="image/jpeg"),
            media_type=GuestUpload.MediaType.IMAGE,
            original_filename="rejected.jpg",
            file_size=8,
            moderation_status=GuestUpload.ModerationStatus.REJECTED,
        )
        self.client.login(username="owner", password="secret")

        response = self.client.get(reverse("events:download_zip", kwargs={"pk": event.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/zip")
        self.assertIn("Memora_reception_zip.zip", response["Content-Disposition"])

        with ZipFile(BytesIO(b"".join(response.streaming_content))) as archive:
            names = archive.namelist()
            self.assertIn("Memora_reception_zip/01_Ceremonie/", names)
            self.assertIn("Memora_reception_zip/06_Piste_de_danse/", names)
            self.assertTrue(
                any(name.startswith("Memora_reception_zip/01_Ceremonie/") and name.endswith("_image.jpg") for name in names)
            )
            self.assertTrue(
                any(name.startswith("Memora_reception_zip/06_Piste_de_danse/") and name.endswith("_video.mp4") for name in names)
            )
            self.assertFalse(any("deleted" in name for name in names))
            self.assertFalse(any("rejected" in name for name in names))

    def test_event_zip_includes_the_guestbook(self):
        from guestbook.models import GuestBookMessage

        event = Event.objects.create(
            organizer=self.user,
            title="Reception Livre",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
        )
        GuestBookMessage.objects.create(
            event=event,
            guest_name="La famille Dupont",
            media_file=SimpleUploadedFile("msg.mp4", b"msg-bytes", content_type="video/mp4"),
            original_filename="msg.mp4",
            file_size=9,
        )
        GuestBookMessage.objects.create(
            event=event,
            media_file="events/x/livre-dor/purged.mp4",
            original_filename="purged.mp4",
            file_size=9,
            media_purged=True,
        )
        self.client.login(username="owner", password="secret")

        response = self.client.get(reverse("events:download_zip", kwargs={"pk": event.pk}))

        with ZipFile(BytesIO(b"".join(response.streaming_content))) as archive:
            names = archive.namelist()
            self.assertIn("Memora_reception_livre/Livre d'or/", names)
            self.assertTrue(
                any("Livre d'or/la_famille_dupont_" in name for name in names)
            )
            self.assertFalse(any("purged" in name for name in names))

    def test_other_organizer_cannot_download_event_zip(self):
        event = Event.objects.create(
            organizer=self.other_user,
            title="Reception Privee",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
        )
        self.client.login(username="owner", password="secret")

        response = self.client.get(reverse("events:download_zip", kwargs={"pk": event.pk}))

        self.assertEqual(response.status_code, 404)

    def test_new_event_type_can_be_used_in_form(self):
        custom_type = EventType.objects.create(
            code="conference",
            label="Conference",
            sort_order=20,
        )
        self.client.login(username="owner", password="secret")

        response = self.client.post(
            reverse("events:create"),
            {
                "title": "Conference Memora",
                "couple_name": "",
                "event_type": custom_type.pk,
                "event_date": "2026-07-10",
                "location": "Lyon",
                "welcome_message": "",
                "is_active": "on",
                "media_retention_days": "45",
            },
        )

        event = Event.objects.get(title="Conference Memora")
        self.assertRedirects(response, reverse("events:detail", kwargs={"pk": event.pk}))
        self.assertEqual(event.event_type, custom_type)


class UpcomingEventTests(TestCase):
    """Evenement paye mais dont le jour n'est pas arrive : page d'attente, puis le
    meme lien mene a la prise de photo/video le jour J."""

    def setUp(self):
        self.organizer = get_user_model().objects.create_user(username="orga-j", password="secret")
        self.event_type = EventType.objects.get(code="wedding")

    def _event(self, days_from_today, paid=True):
        event = Event.objects.create(
            organizer=self.organizer,
            title="Mariage Jour J",
            couple_name="Beny & Deborah",
            event_type=self.event_type,
            event_date=timezone.localdate() + timedelta(days=days_from_today),
        )
        if paid:
            event.mark_paid(provider="test")
            event.save(update_fields=["payment_status", "paid_at", "payment_provider"])
        return event

    def _upload_url(self, event):
        return reverse("uploads:create", kwargs={"slug": event.slug, "access_key": event.public_access_key})

    def test_qr_link_shows_a_waiting_page_before_the_day(self):
        event = self._event(days_from_today=3)

        response = self.client.get(event.get_public_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Rendez-vous le")
        self.assertContains(response, "Beny &amp; Deborah")
        self.assertContains(response, "data-opens-at=")
        self.assertContains(response, "event-opens.js")
        self.assertNotContains(response, "start-camera-photo-button")
        self.assertNotContains(response, "site-footer")

    def test_upload_page_and_upload_are_closed_before_the_day(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        event = self._event(days_from_today=3)

        get_response = self.client.get(self._upload_url(event))
        post_response = self.client.post(
            self._upload_url(event),
            {"media_file": SimpleUploadedFile("p.jpg", b"img", content_type="image/jpeg")},
        )

        self.assertContains(get_response, "Rendez-vous le")
        self.assertContains(post_response, "Rendez-vous le")
        self.assertEqual(GuestUpload.objects.filter(event=event).count(), 0)

    def test_the_same_link_opens_the_camera_on_the_day(self):
        event = self._event(days_from_today=0)

        response = self.client.get(event.get_public_url())

        self.assertRedirects(response, self._upload_url(event), fetch_redirect_response=False)
        self.assertContains(self.client.get(self._upload_url(event)), "start-camera-photo-button")

    def test_organizer_and_staff_can_try_the_guest_flow_before_the_day(self):
        event = self._event(days_from_today=5)

        self.client.login(username="orga-j", password="secret")
        self.assertContains(self.client.get(self._upload_url(event)), "start-camera-photo-button")

        self.client.logout()
        get_user_model().objects.create_user(username="equipe", password="secret", is_staff=True)
        self.client.login(username="equipe", password="secret")
        self.assertContains(self.client.get(self._upload_url(event)), "start-camera-photo-button")

        # Un autre organisateur, lui, voit la page d'attente.
        self.client.logout()
        get_user_model().objects.create_user(username="autre", password="secret")
        self.client.login(username="autre", password="secret")
        self.assertContains(self.client.get(self._upload_url(event)), "Rendez-vous le")

    def test_an_unpaid_event_still_says_it_is_not_activated(self):
        event = self._event(days_from_today=3, paid=False)

        response = self.client.get(event.get_public_url())

        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "pas encore activé", status_code=403)

    def test_is_upcoming_follows_the_event_date(self):
        self.assertTrue(self._event(days_from_today=1).is_upcoming)
        self.assertFalse(self._event(days_from_today=0).is_upcoming)
        self.assertFalse(self._event(days_from_today=-2).is_upcoming)


class QrKitTests(TestCase):
    """Pack QR : le QR en grand, la phrase d'invitation et la marque Memora, sur fond transparent."""

    URL = "https://memoracd.site/e/mariage-qr/cle/"

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="orga-qr", password="secret")
        self.event = Event.objects.create(
            organizer=self.user,
            title="Mariage QR",
            event_type=EventType.objects.get(code="wedding"),
            event_date=date(2026, 7, 8),
        )
        self.client.login(username="orga-qr", password="secret")
        self.configuration = SiteConfiguration.current()
        self.configuration.support_email = "contact@memoracd.site"
        self.configuration.support_whatsapp = "+243 990 000 000"
        self.configuration.save()
        self.contacts = brand_contact_items(self.configuration)

    def _kit(self):
        return zipfile.ZipFile(BytesIO(build_qr_kit_zip(self.URL, "mariage-qr", self.configuration)))

    def test_download_is_a_zip_attachment(self):
        response = self.client.get(reverse("events:qr_kit", kwargs={"pk": self.event.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/zip")
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertIn(f"memora-qr-{self.event.slug}.zip", response["Content-Disposition"])
        self.assertTrue(zipfile.is_zipfile(BytesIO(response.content)))

    def test_kit_holds_every_format_layout_and_colour(self):
        names = self._kit().namelist()

        for colour, background in (("noir-pour-fonds-clairs", "fond-blanc"), ("blanc-pour-fonds-fonces", "fond-noir")):
            for layout in ("portrait", "paysage-16x9", "carre"):
                base = f"memora-qr-mariage-qr/{colour}/{layout}/qr-{layout}"
                for suffix in (".svg", ".pdf", "-transparent.png", f"-{background}.png"):
                    self.assertIn(base + suffix, names)
        self.assertIn("memora-qr-mariage-qr/LISEZ-MOI.txt", names)
        self.assertEqual(len(names), 25)

    def test_svg_is_vector_with_outlined_text_and_no_background(self):
        archive = self._kit()
        for name in archive.namelist():
            if not name.endswith(".svg"):
                continue
            svg = archive.read(name).decode("utf-8")
            ElementTree.fromstring(svg)  # XML valide
            self.assertNotIn("<text", svg)  # texte en courbes : aucune police a installer
            self.assertNotIn("<image", svg)
            self.assertIn('id="logo"', svg)  # la marque est toujours presente
        black = archive.read("memora-qr-mariage-qr/noir-pour-fonds-clairs/portrait/qr-portrait.svg").decode()
        white = archive.read("memora-qr-mariage-qr/blanc-pour-fonds-fonces/portrait/qr-portrait.svg").decode()
        self.assertIn('fill="#000000"', black)
        self.assertIn('fill="#ffffff"', white)
        self.assertNotIn("<rect width", black)  # pas de rectangle de fond

    def test_pdf_is_one_vector_page_printed_in_pure_black_ink(self):
        archive = self._kit()
        black = archive.read("memora-qr-mariage-qr/noir-pour-fonds-clairs/portrait/qr-portrait.pdf")
        landscape = archive.read("memora-qr-mariage-qr/noir-pour-fonds-clairs/paysage-16x9/qr-paysage-16x9.pdf")

        self.assertTrue(black.startswith(b"%PDF-1.4"))
        self.assertTrue(black.rstrip().endswith(b"%%EOF"))
        self.assertIn(b"/MediaBox [0 0 595.276 841.890]", black)  # A4 portrait
        self.assertIn(b"/MediaBox [0 0 841.890 473.563]", landscape)  # 297 mm, 16:9
        self.assertNotIn(b"/Image", black)
        content = zlib.decompress(black.split(b"stream\n", 1)[1].split(b"\nendstream", 1)[0]).decode("ascii")
        self.assertTrue(content.startswith("0 0 0 1 k"))  # noir K seul, pas de noir quadrichromie

    def test_transparent_png_has_no_background_and_reproduces_every_module(self):
        matrix = qr_matrix(self.URL)
        archive = self._kit()
        for layout_name, build in (
            ("portrait", portrait_layout),
            ("carre", square_layout),
            ("paysage-16x9", landscape_layout),
        ):
            layout = build(matrix, self.contacts)
            path = f"memora-qr-mariage-qr/noir-pour-fonds-clairs/{layout_name}/qr-{layout_name}-transparent.png"
            image = Image.open(BytesIO(archive.read(path)))
            self.assertEqual(image.mode, "RGBA")
            self.assertEqual(image.size[0], layout.png_width)
            alpha = image.getchannel("A")
            self.assertEqual(alpha.getpixel((0, 0)), 0)
            self.assertEqual(alpha.getpixel((image.width - 1, image.height - 1)), 0)

            scale = image.width / layout.width
            _, x, y, size = next(item for item in layout.items if item[0] == "qr")
            unit = size / len(matrix)
            for row in range(len(matrix)):
                for col in range(len(matrix)):
                    centre = (round((x + (col + 0.5) * unit) * scale), round((y + (row + 0.5) * unit) * scale))
                    self.assertEqual(alpha.getpixel(centre) > 127, matrix[row][col], (layout_name, row, col))

    def test_nothing_is_drawn_in_the_quiet_zone_around_the_code(self):
        matrix = qr_matrix(self.URL)
        for build in (portrait_layout, square_layout, landscape_layout):
            layout = build(matrix, self.contacts)
            mask = render_mask(layout, matrix, width_px=1000)
            scale = mask.width / layout.width
            _, x, y, size = next(item for item in layout.items if item[0] == "qr")
            quiet = 4 * size / len(matrix)  # zone de silence normalisee : 4 modules
            inner = (round(x * scale) - 2, round(y * scale) - 2, round((x + size) * scale) + 2, round((y + size) * scale) + 2)
            zone = (
                max(round((x - quiet) * scale), 0),
                max(round((y - quiet) * scale), 0),
                min(round((x + size + quiet) * scale), mask.width),
                min(round((y + size + quiet) * scale), mask.height),
            )
            pixels = mask.load()
            for py in range(zone[1], zone[3]):
                for px in range(zone[0], zone[2]):
                    inside_code = inner[0] <= px <= inner[2] and inner[1] <= py <= inner[3]
                    self.assertTrue(inside_code or pixels[px, py] < 30, (build.__name__, px, py))

    def test_brand_is_always_present_below_the_code(self):
        layout = portrait_layout(qr_matrix(self.URL), self.contacts)
        _, _, qr_y, qr_size = next(item for item in layout.items if item[0] == "qr")

        self.assertEqual([item[0] for item in layout.items].count("mark"), 1)
        self.assertTrue(any(item[0] == "text" and item[2] == "Memora" for item in layout.items))
        self.assertTrue(any(item[0] == "text" and item[2].startswith("Revivez votre") for item in layout.items))
        below = [item for item in layout.items if item[0] == "text" and item[5] > qr_y + qr_size]
        self.assertGreaterEqual(len(below), 3)

    def test_the_layouts_fit_their_page(self):
        matrix = qr_matrix(self.URL)
        for build in (portrait_layout, square_layout, landscape_layout):
            layout = build(matrix, self.contacts)
            mask = render_mask(layout, matrix, width_px=800)
            left, top, right, bottom = mask.getbbox()
            self.assertGreaterEqual(left, 0.04 * mask.width, build.__name__)
            self.assertGreaterEqual(top, 0.04 * mask.height, build.__name__)
            self.assertLessEqual(right, 0.96 * mask.width, build.__name__)
            self.assertLessEqual(bottom, 0.96 * mask.height, build.__name__)

    def test_contact_line_lists_only_what_is_filled_in(self):
        with override_settings(MEMORA_PUBLIC_BASE_URL="https://memoracd.site"):
            self.assertEqual(
                brand_contact_items(self.configuration),
                ["memoracd.site", "contact@memoracd.site", "WhatsApp +243 990 000 000"],
            )
            self.configuration.support_email = ""
            self.configuration.legal_contact_email = ""
            self.configuration.support_whatsapp = ""
            self.assertEqual(brand_contact_items(self.configuration), ["memoracd.site"])

    def test_a_compact_congolese_number_is_grouped_for_reading(self):
        self.configuration.support_whatsapp = "+243842616570"

        self.assertIn("WhatsApp +243 842 616 570", brand_contact_items(self.configuration))

    def test_dashboard_offers_a_single_download_button(self):
        self.event.mark_paid(provider="test")
        self.event.save(update_fields=["payment_status", "paid_at", "payment_provider"])

        response = self.client.get(reverse("events:detail", kwargs={"pk": self.event.pk}))

        self.assertContains(response, reverse("events:qr_kit", kwargs={"pk": self.event.pk}))
        self.assertContains(response, "Télécharger le QR code")
        self.assertNotContains(response, "Fiche à imprimer")

    def test_kit_and_preview_are_limited_to_the_organizer(self):
        get_user_model().objects.create_user(username="autre-qr", password="secret")
        self.client.login(username="autre-qr", password="secret")
        for name in ("events:qr_kit", "events:qr_code"):
            self.assertEqual(self.client.get(reverse(name, kwargs={"pk": self.event.pk})).status_code, 404)

        response = self.client_class().get(reverse("events:qr_kit", kwargs={"pk": self.event.pk}))
        self.assertEqual(response.status_code, 302)
        self.assertIn("connexion", response["Location"])

    def test_preview_is_an_inline_portrait_png(self):
        response = self.client.get(reverse("events:qr_code", kwargs={"pk": self.event.pk}))

        self.assertEqual(response["Content-Type"], "image/png")
        self.assertIn("inline", response["Content-Disposition"])
        image = Image.open(BytesIO(response.content))
        self.assertGreater(image.height, image.width)

    def test_readme_explains_how_to_choose_and_keep_the_code_scannable(self):
        readme = self._kit().read("memora-qr-mariage-qr/LISEZ-MOI.txt").decode("utf-8")

        for phrase in ("noir-pour-fonds-clairs", "blanc-pour-fonds-fonces", "portrait", "paysage-16x9", "carre", "zone UNIE"):
            self.assertIn(phrase, readme)


class BrandAssetsTests(TestCase):
    """Visuels de marque pour les reseaux : trois SVG maitres aux couleurs de la charte."""

    def test_svg_masters_are_valid_outlined_and_on_the_charter_colours(self):
        for name, (build, width, height) in ASSETS.items():
            svg = build()
            root = ElementTree.fromstring(svg)
            self.assertEqual(root.get("viewBox"), f"0 0 {width} {height}", name)
            self.assertNotIn("<text", svg, name)  # texte en courbes
            self.assertIn("#241f22", svg, name)  # encre de la charte
            self.assertIn("#f4d9d5", svg, name)  # monogramme

    def test_the_banner_carries_logo_name_and_slogan_inside_the_central_band(self):
        svg = ASSETS["memora-banniere"][0]()

        self.assertIn('aria-label="Memora"', svg)
        self.assertIn("Revivez votre événement à travers les yeux de vos invités.", svg)
        self.assertIn("#d8b46a", svg)  # ornement champagne
        self.assertEqual(ASSETS["memora-banniere"][1:], (3000, 1000))

    def test_icon_is_a_full_bleed_square(self):
        _, width, height = ASSETS["memora-logo-icone"]

        self.assertEqual(width, height)
        self.assertNotRegex(ASSETS["memora-logo-icone"][0](), r"<rect[^>]*rx=")  # pas de coins arrondis : la plateforme decoupe


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class ResetEventContentTests(TestCase):
    """Vider un evenement de test : tout le contenu part, l'evenement et son QR code restent."""

    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(username="admin-reset", email="a@b.c", password="secret")
        organizer = get_user_model().objects.create_user(username="orga-reset", password="secret")
        agent = get_user_model().objects.create_user(username="agent-reset", password="secret")
        AgentProfile.objects.create(user=agent)
        self.event = Event.objects.create(
            organizer=organizer,
            title="Mariage a vider",
            event_type=EventType.objects.get(code="wedding"),
            event_date=timezone.localdate() + timedelta(days=5),
            welcome_message="Bienvenue",
        )
        self.event.mark_paid(provider="test")
        self.event.cover_image.save("cover.jpg", SimpleUploadedFile("cover.jpg", b"cover"), save=False)
        self.event.guest_preview_enabled = True
        self.event.save()
        category = self.event.upload_categories.first()
        self.upload = GuestUpload(
            event=self.event,
            category=category,
            media_type=GuestUpload.MediaType.IMAGE,
            original_filename="p.jpg",
            file_size=5,
        )
        self.upload.media_file.save("p.jpg", SimpleUploadedFile("p.jpg", b"photo"), save=True)
        self.movie = GeneratedMovie(event=self.event, status=GeneratedMovie.Status.COMPLETED)
        self.movie.final_file.save("film.mp4", SimpleUploadedFile("film.mp4", b"film"), save=False)
        self.movie.save()
        self.message = GuestBookMessage(event=self.event, original_filename="m.mp4", file_size=3, recorded_by=agent)
        self.message.media_file.save("m.mp4", SimpleUploadedFile("m.mp4", b"msg"), save=True)
        self.montage = GuestBookMovie(event=self.event)
        self.montage.final_file.save("montage.mp4", SimpleUploadedFile("montage.mp4", b"montage"), save=False)
        self.montage.save()
        self.assignment = GuestBookAssignment.objects.create(
            event=self.event, agent=agent, started_at=timezone.now(), ended_at=timezone.now()
        )
        self.change_url = reverse("admin:events_event_change", args=[self.event.pk])
        self.reset_url = reverse("admin:events_event_reset_content", args=[self.event.pk])

    def _stored(self, field):
        return field.storage.exists(field.name)

    def test_reset_removes_all_content_and_keeps_the_event_and_its_qr_code(self):
        before = (self.event.slug, self.event.public_access_key, self.event.get_public_url())
        cover_name = self.event.cover_image.name
        # Noms relevés avant : un champ vidé perd son nom.
        files = [
            (field.storage, field.name)
            for field in (self.upload.media_file, self.movie.final_file, self.message.media_file, self.montage.final_file)
        ]
        self.assertTrue(all(storage.exists(name) for storage, name in files))

        counts = reset_event_content(self.event)

        self.assertEqual(
            counts, {"uploads": 1, "movies": 1, "guestbook_messages": 1, "guestbook_movie": 1, "files": 4}
        )
        self.assertFalse(any(storage.exists(name) for storage, name in files))
        self.assertFalse(self.event.guest_uploads.exists())
        self.assertFalse(self.event.generated_movies.exists())
        self.assertFalse(self.event.guestbook_messages.exists())
        self.assertFalse(GuestBookMovie.objects.filter(event=self.event).exists())
        # L'evenement, son lien (donc le QR code imprime) et son reglage sont intacts.
        self.event.refresh_from_db()
        self.assertEqual((self.event.slug, self.event.public_access_key, self.event.get_public_url()), before)
        self.assertEqual(self.event.cover_image.name, cover_name)
        self.assertTrue(self._stored(self.event.cover_image))
        self.assertTrue(self.event.is_paid)
        self.assertTrue(self.event.guest_preview_enabled)
        self.assertEqual(self.event.welcome_message, "Bienvenue")
        self.assertTrue(self.event.upload_categories.exists())
        # La mission de l'agent est remise a « a demarrer ».
        self.assignment.refresh_from_db()
        self.assertIsNone(self.assignment.started_at)
        self.assertIsNone(self.assignment.ended_at)

    def test_the_guest_link_still_works_after_the_reset(self):
        create_url = reverse(
            "uploads:create", kwargs={"slug": self.event.slug, "access_key": self.event.public_access_key}
        )
        reset_event_content(self.event)

        self.assertContains(self.client.get(create_url), "start-camera-photo-button")

    def test_a_real_event_outside_test_mode_is_never_emptied(self):
        self.event.guest_preview_enabled = False
        self.event.save()

        with self.assertRaises(EventResetRefused):
            reset_event_content(self.event)

        self.assertTrue(self.event.guest_uploads.exists())
        self.assertTrue(self._stored(self.upload.media_file))

    def test_button_shows_only_in_test_mode_and_needs_the_typed_confirmation(self):
        self.client.login(username="admin-reset", password="secret")
        self.assertContains(self.client.get(self.change_url), "Vider le contenu de test")

        self.client.post(self.reset_url, {"confirm": "oui"})
        self.assertTrue(self.event.guest_uploads.exists())

        response = self.client.post(self.reset_url, {"confirm": "VIDER"}, follow=True)
        self.assertRedirects(response, self.change_url)
        self.assertFalse(self.event.guest_uploads.exists())
        self.assertContains(response, "Contenu de test supprime")
        self.assertContains(response, "QR code sont inchanges")

        self.event.guest_preview_enabled = False
        self.event.save()
        self.assertNotContains(self.client.get(self.change_url), "Vider le contenu de test")

    def test_admin_view_refuses_a_real_event_and_anonymous_visitors(self):
        self.event.guest_preview_enabled = False
        self.event.save()
        self.client.login(username="admin-reset", password="secret")

        response = self.client.post(self.reset_url, {"confirm": "VIDER"}, follow=True)
        self.assertContains(response, "Par securite")
        self.assertTrue(self.event.guest_uploads.exists())

        self.assertEqual(self.client.get(self.reset_url).status_code, 405)
        anonymous = self.client_class().post(self.reset_url, {"confirm": "VIDER"})
        self.assertEqual(anonymous.status_code, 302)
        self.assertIn("/admin/login/", anonymous["Location"])

    def test_command_previews_then_deletes_and_refuses_real_events(self):
        out = StringIO()
        call_command("reset_event_content", str(self.event.pk), stdout=out)
        self.assertIn("Apercu seulement", out.getvalue())
        self.assertTrue(self.event.guest_uploads.exists())

        out = StringIO()
        call_command("reset_event_content", str(self.event.pk), "--yes", stdout=out)
        self.assertIn("SUPPRIME : 1 souvenir(s)", out.getvalue())
        self.assertIn(self.event.get_public_url(), out.getvalue())
        self.assertFalse(self.event.guest_uploads.exists())

        Event.objects.filter(pk=self.event.pk).update(guest_preview_enabled=False)
        with self.assertRaises(CommandError):
            call_command("reset_event_content", str(self.event.pk), "--yes", stdout=StringIO())


class GuestTestAdminTests(TestCase):
    """Bouton admin « Activer pour test » : ouvre la collecte avant le jour J."""

    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(username="admin-t", email="a@b.c", password="secret")
        organizer = get_user_model().objects.create_user(username="orga-t", password="secret")
        self.event = Event.objects.create(
            organizer=organizer,
            title="Mariage Test Admin",
            event_type=EventType.objects.get(code="wedding"),
            event_date=timezone.localdate() + timedelta(days=9),
        )
        self.event.mark_paid(provider="test")
        self.event.save(update_fields=["payment_status", "paid_at", "payment_provider"])
        self.toggle_url = reverse("admin:events_event_toggle_guest_test", args=[self.event.pk])
        self.upload_url = reverse(
            "uploads:create", kwargs={"slug": self.event.slug, "access_key": self.event.public_access_key}
        )

    def test_change_page_offers_the_test_button(self):
        self.client.login(username="admin-t", password="secret")

        response = self.client.get(reverse("admin:events_event_change", args=[self.event.pk]))

        self.assertContains(response, "Activer pour test")
        self.assertContains(response, self.toggle_url)

    def test_button_opens_then_closes_the_event_to_guests(self):
        self.client.login(username="admin-t", password="secret")
        guest = self.client_class()
        self.assertContains(guest.get(self.upload_url), "Rendez-vous le")

        response = self.client.post(self.toggle_url)
        self.assertRedirects(response, reverse("admin:events_event_change", args=[self.event.pk]))
        self.event.refresh_from_db()
        self.assertTrue(self.event.guest_preview_enabled)
        # Un invite (non connecte) accede desormais a la prise de photo/video.
        self.assertContains(guest.get(self.upload_url), "start-camera-photo-button")
        self.assertContains(
            self.client.get(reverse("admin:events_event_change", args=[self.event.pk])),
            "Refermer le test invités",
        )

        self.client.post(self.toggle_url)
        self.event.refresh_from_db()
        self.assertFalse(self.event.guest_preview_enabled)
        self.assertContains(guest.get(self.upload_url), "Rendez-vous le")

    def test_toggle_requires_post_and_an_admin_session(self):
        self.client.login(username="admin-t", password="secret")
        self.assertEqual(self.client.get(self.toggle_url).status_code, 405)

        anonymous = self.client_class()
        response = anonymous.post(self.toggle_url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response["Location"])
        self.event.refresh_from_db()
        self.assertFalse(self.event.guest_preview_enabled)

    def test_list_actions_open_and_close_several_events(self):
        self.client.login(username="admin-t", password="secret")
        changelist = reverse("admin:events_event_changelist")

        self.client.post(changelist, {"action": "open_for_guest_test", "_selected_action": [self.event.pk]})
        self.event.refresh_from_db()
        self.assertTrue(self.event.guest_preview_enabled)

        self.client.post(changelist, {"action": "close_guest_test", "_selected_action": [self.event.pk]})
        self.event.refresh_from_db()
        self.assertFalse(self.event.guest_preview_enabled)

    def test_the_test_flag_only_matters_before_the_day(self):
        self.event.guest_preview_enabled = True
        self.assertFalse(self.event.is_upcoming)
        self.event.guest_preview_enabled = False
        self.assertTrue(self.event.is_upcoming)


class PurgeEventMediaTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="owner-purge", password="secret")
        self.event_type = EventType.objects.get(code="wedding")
        self.event = Event.objects.create(
            organizer=self.user,
            title="Mariage Purge",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
        )

    def _fill(self):
        from guestbook.models import GuestBookMessage, GuestBookMovie

        category = self.event.upload_categories.first()
        upload = GuestUpload.objects.create(
            event=self.event,
            category=category,
            media_file=SimpleUploadedFile("p.jpg", b"img", content_type="image/jpeg"),
            media_type=GuestUpload.MediaType.IMAGE,
            original_filename="p.jpg",
            file_size=3,
        )
        message = GuestBookMessage.objects.create(
            event=self.event,
            media_file=SimpleUploadedFile("m.mp4", b"vid", content_type="video/mp4"),
            original_filename="m.mp4",
            file_size=3,
        )
        movie = GeneratedMovie.objects.create(
            event=self.event,
            status=GeneratedMovie.Status.COMPLETED,
            final_file=SimpleUploadedFile("f.mp4", b"mov", content_type="video/mp4"),
        )
        montage = GuestBookMovie.objects.create(
            event=self.event,
            status=GuestBookMovie.Status.COMPLETED,
            final_file=SimpleUploadedFile("g.mp4", b"mov", content_type="video/mp4"),
        )
        return upload, message, movie, montage

    def test_purge_event_media_clears_every_file_but_keeps_rows(self):
        from events.services import purge_event_media

        upload, message, movie, montage = self._fill()

        counts = purge_event_media(self.event)

        for obj in (upload, message, movie, montage):
            obj.refresh_from_db()
        self.assertFalse(upload.media_file)
        self.assertTrue(upload.media_purged)
        self.assertFalse(message.media_file)
        self.assertTrue(message.media_purged)
        self.assertFalse(movie.final_file)
        self.assertTrue(movie.media_purged)
        self.assertFalse(montage.final_file)
        self.assertEqual(counts["uploads"], 1)
        self.assertEqual(counts["guestbook"], 1)
        self.assertGreaterEqual(counts["deliverables"], 2)
        # Les lignes restent (pierres tombales).
        self.assertTrue(Event.objects.filter(pk=self.event.pk).exists())
        self.assertEqual(self.event.guest_uploads.count(), 1)

    def test_purge_event_media_also_removes_the_organizers_song(self):
        from django.core.files.base import ContentFile

        from events.services import purge_event_media

        self.event.custom_music_file.save("chanson.mp3", ContentFile(b"song"), save=True)
        storage, name = self.event.custom_music_file.storage, self.event.custom_music_file.name
        self.assertTrue(storage.exists(name))

        counts = purge_event_media(self.event)

        self.event.refresh_from_db()
        self.assertFalse(self.event.custom_music_file)
        self.assertFalse(storage.exists(name))
        self.assertGreaterEqual(counts["event"], 1)

    def test_admin_delete_purges_r2_then_removes_event(self):
        from django.contrib.admin.sites import AdminSite

        from events.admin import EventAdmin

        upload, _, movie, _ = self._fill()
        movie_pk, upload_pk = movie.pk, upload.pk
        admin_instance = EventAdmin(Event, AdminSite())

        admin_instance.delete_model(request=None, obj=self.event)

        self.assertFalse(Event.objects.filter(pk=self.event.pk).exists())
        self.assertFalse(GeneratedMovie.objects.filter(pk=movie_pk).exists())
        self.assertFalse(GuestUpload.objects.filter(pk=upload_pk).exists())


class PaymentReceiptEmailTests(TestCase):
    """Recu de paiement envoye a l'organisateur apres confirmation en admin."""

    def setUp(self):
        cache.clear()
        self.organizer = get_user_model().objects.create_user(
            username="orga-recu", email="orga-recu@example.com", password="secret"
        )
        self.event_type, _ = EventType.objects.get_or_create(
            code="wedding", defaults={"label": "Mariage", "sort_order": 1}
        )
        self.event = Event.objects.create(
            organizer=self.organizer,
            title="Mariage Recu",
            event_type=self.event_type,
            event_date=date(2026, 7, 12),
            price_amount=7900,
            price_currency="USD",
        )

    def test_sends_receipt_after_payment_confirmed(self):
        from django.core import mail

        from events.services import send_payment_receipt_email

        self.event.mark_paid(reference="ref-001", provider="manual-admin")
        self.event.save()

        sent = send_payment_receipt_email(self.event)

        self.assertTrue(sent)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.organizer.email, mail.outbox[0].to)
        self.assertIn("Mariage Recu", mail.outbox[0].subject)
        self.assertIn("ref-001", mail.outbox[0].body)
        self.event.refresh_from_db()
        self.assertIsNotNone(self.event.receipt_sent_at)

    def test_does_not_send_twice(self):
        from django.core import mail

        from events.services import send_payment_receipt_email

        self.event.mark_paid()
        self.event.save()
        send_payment_receipt_email(self.event)

        sent_again = send_payment_receipt_email(self.event)

        self.assertFalse(sent_again)
        self.assertEqual(len(mail.outbox), 1)

    def test_skips_unpaid_event(self):
        from events.services import send_payment_receipt_email

        sent = send_payment_receipt_email(self.event)

        self.assertFalse(sent)

    def test_skips_organizer_without_email(self):
        from events.services import send_payment_receipt_email

        self.organizer.email = ""
        self.organizer.save()
        self.event.mark_paid()
        self.event.save()

        sent = send_payment_receipt_email(self.event)

        self.assertFalse(sent)

    def test_admin_action_marks_paid_and_sends_receipt(self):
        from django.core import mail

        response = self._run_mark_paid_action()

        self.assertEqual(response.status_code, 302)
        self.event.refresh_from_db()
        self.assertTrue(self.event.is_paid)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIsNotNone(self.event.receipt_sent_at)

    def _run_mark_paid_action(self):
        admin_user = get_user_model().objects.create_superuser(
            username="admin-recu", email="admin@example.com", password="secret"
        )
        self.client.force_login(admin_user)
        return self.client.post(
            reverse("admin:events_event_changelist"),
            {
                "action": "mark_events_paid",
                "_selected_action": [str(self.event.pk)],
            },
            follow=False,
        )
