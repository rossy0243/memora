from datetime import date
import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from events.models import Event, EventType

from .models import GuestUpload, UploadCategory

TEST_MEDIA_ROOT = tempfile.mkdtemp()


class UploadCategoryTests(TestCase):
    def setUp(self):
        self.organizer = get_user_model().objects.create_user(
            username="organizer",
            password="secret",
        )
        self.event_type = EventType.objects.get(code="wedding")

    def test_default_moment_categories_are_created_for_each_event(self):
        expected_codes = [
            "ceremony",
            "arrival",
            "cocktail",
            "reception",
            "speech",
            "dancefloor",
            "cake",
            "funny",
            "emotional",
            "other",
        ]
        first_event = Event.objects.create(
            organizer=self.organizer,
            title="Premier evenement",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
        )
        second_event = Event.objects.create(
            organizer=self.organizer,
            title="Second evenement",
            event_type=self.event_type,
            event_date=date(2026, 7, 9),
        )

        self.assertEqual(
            list(first_event.upload_categories.order_by("sort_order").values_list("code", flat=True)),
            expected_codes,
        )
        self.assertEqual(
            list(second_event.upload_categories.order_by("sort_order").values_list("code", flat=True)),
            expected_codes,
        )

    def test_event_categories_are_independent(self):
        first_event = Event.objects.create(
            organizer=self.organizer,
            title="Premier evenement",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
        )
        second_event = Event.objects.create(
            organizer=self.organizer,
            title="Second evenement",
            event_type=self.event_type,
            event_date=date(2026, 7, 9),
        )

        first_event.upload_categories.filter(code="ceremony").update(label="Mairie")

        self.assertEqual(first_event.upload_categories.get(code="ceremony").label, "Mairie")
        self.assertEqual(second_event.upload_categories.get(code="ceremony").label, "Ceremonie")


class GuestUploadModelTests(TestCase):
    def setUp(self):
        organizer = get_user_model().objects.create_user(
            username="organizer",
            password="secret",
        )
        event_type = EventType.objects.get(code="wedding")
        self.event = Event.objects.create(
            organizer=organizer,
            title="Soiree Memora",
            event_type=event_type,
            event_date=date(2026, 7, 8),
        )
        self.category = self.event.upload_categories.get(code="dancefloor")

    def test_guest_upload_keeps_guest_metadata_without_account(self):
        upload = GuestUpload.objects.create(
            event=self.event,
            category=self.category,
            media_file="events/soiree-memora/uploads/dancefloor/video.mov",
            media_type=GuestUpload.MediaType.VIDEO,
            original_filename="IMG_1234.MOV",
            file_size=42_000_000,
            ip_address="127.0.0.1",
            user_agent="Mobile Safari",
            session_key="guest-session",
        )

        self.assertEqual(upload.extension, "mov")
        self.assertFalse(upload.is_deleted)
        self.assertFalse(upload.is_selected_for_movie)


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class GuestUploadViewTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        organizer = get_user_model().objects.create_user(
            username="organizer",
            password="secret",
        )
        self.event_type = EventType.objects.get(code="wedding")
        self.event = Event.objects.create(
            organizer=organizer,
            title="Mariage Test",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
        )
        self.category = self.event.upload_categories.get(code="ceremony")

    def test_guest_can_upload_memory_without_account(self):
        media = SimpleUploadedFile("photo.jpg", b"fake-image", content_type="image/jpeg")

        response = self.client.post(
            reverse("uploads:create", kwargs={"slug": self.event.slug}),
            {
                "media_file": media,
                "category": self.category.pk,
            },
        )

        self.assertRedirects(response, reverse("uploads:thanks", kwargs={"slug": self.event.slug}))
        upload = GuestUpload.objects.get(event=self.event)
        self.assertEqual(upload.media_type, GuestUpload.MediaType.IMAGE)
        self.assertEqual(upload.original_filename, "photo.jpg")
        self.assertTrue(upload.session_key)

    def test_rejects_invalid_file_extension(self):
        media = SimpleUploadedFile("notes.pdf", b"pdf", content_type="application/pdf")

        response = self.client.post(
            reverse("uploads:create", kwargs={"slug": self.event.slug}),
            {
                "media_file": media,
                "category": self.category.pk,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ce format n&#x27;est pas accepte.")
        self.assertEqual(GuestUpload.objects.count(), 0)

    def test_rejects_category_from_another_event(self):
        other_event = Event.objects.create(
            organizer=self.event.organizer,
            title="Autre mariage",
            event_type=self.event_type,
            event_date=date(2026, 7, 9),
        )
        other_category = other_event.upload_categories.get(code="ceremony")
        media = SimpleUploadedFile("photo.jpg", b"fake-image", content_type="image/jpeg")

        response = self.client.post(
            reverse("uploads:create", kwargs={"slug": self.event.slug}),
            {
                "media_file": media,
                "category": other_category.pk,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(GuestUpload.objects.count(), 0)

    @override_settings(MEMORA_MAX_UPLOAD_SIZE=4)
    def test_rejects_oversized_file(self):
        media = SimpleUploadedFile("video.mp4", b"12345", content_type="video/mp4")

        response = self.client.post(
            reverse("uploads:create", kwargs={"slug": self.event.slug}),
            {
                "media_file": media,
                "category": self.category.pk,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Cette video est trop lourde.")
        self.assertEqual(GuestUpload.objects.count(), 0)

    @override_settings(MEMORA_SESSION_UPLOAD_LIMIT=1)
    def test_limits_uploads_by_session(self):
        first_media = SimpleUploadedFile("first.jpg", b"first", content_type="image/jpeg")
        second_media = SimpleUploadedFile("second.jpg", b"second", content_type="image/jpeg")

        self.client.post(
            reverse("uploads:create", kwargs={"slug": self.event.slug}),
            {
                "media_file": first_media,
                "category": self.category.pk,
            },
        )
        response = self.client.post(
            reverse("uploads:create", kwargs={"slug": self.event.slug}),
            {
                "media_file": second_media,
                "category": self.category.pk,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Vous avez deja envoye beaucoup de souvenirs")
        self.assertEqual(GuestUpload.objects.count(), 1)
