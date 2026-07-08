from datetime import date
from io import BytesIO
import shutil
import tempfile
from zipfile import ZipFile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from uploads.models import GuestUpload, UploadCategory

from .models import Event, EventType

TEST_MEDIA_ROOT = tempfile.mkdtemp()


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
                "is_active": "on",
                "media_retention_days": "90",
            },
        )

        event = Event.objects.get(title="Mariage de Lea et Sam")
        self.assertRedirects(response, reverse("events:detail", kwargs={"pk": event.pk}))
        self.assertEqual(event.organizer, self.user)
        self.assertEqual(event.slug, "mariage-de-lea-et-sam")
        self.assertTrue(event.qr_code_image.name.endswith("mariage-de-lea-et-sam-qr.png"))

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

    def test_public_event_page_uses_slug(self):
        event = Event.objects.create(
            organizer=self.user,
            title="Reception Memora",
            couple_name="Lea & Sam",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
            welcome_message="Bienvenue dans nos souvenirs.",
        )

        response = self.client.get(reverse("public_event", kwargs={"slug": event.slug}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Lea &amp; Sam")
        self.assertContains(response, "Bienvenue dans nos souvenirs.")

    def test_event_detail_displays_media_dashboard(self):
        event = Event.objects.create(
            organizer=self.user,
            title="Reception Dashboard",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
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
        )
        GuestUpload.objects.create(
            event=event,
            category=dancefloor,
            media_file="events/reception-dashboard/uploads/dancefloor/video.mp4",
            media_type=GuestUpload.MediaType.VIDEO,
            original_filename="video.mp4",
            file_size=456,
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
        self.assertContains(response, "Medias invites")
        self.assertContains(response, "photo.jpg")
        self.assertContains(response, "video.mp4")
        self.assertNotContains(response, "deleted.jpg")
        self.assertEqual(response.context["media_stats"]["total"], 2)
        self.assertEqual(response.context["media_stats"]["photos"], 1)
        self.assertEqual(response.context["media_stats"]["videos"], 1)

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
        )
        GuestUpload.objects.create(
            event=event,
            category=dancefloor,
            media_file=SimpleUploadedFile("video.mp4", b"video-bytes", content_type="video/mp4"),
            media_type=GuestUpload.MediaType.VIDEO,
            original_filename="video.mp4",
            file_size=11,
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
        self.client.login(username="owner", password="secret")

        response = self.client.get(reverse("events:download_zip", kwargs={"pk": event.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/zip")
        self.assertIn("Memora_reception_zip.zip", response["Content-Disposition"])

        with ZipFile(BytesIO(response.content)) as archive:
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
