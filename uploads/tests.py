from datetime import date
import shutil
import tempfile
from unittest.mock import patch

from django import forms
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from events.models import Event, EventType

from .models import GuestUpload, UploadCategory, UploadCategoryTemplate

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

    def test_event_categories_are_copied_from_event_type_templates(self):
        brunch_type = EventType.objects.create(
            code="brunch",
            label="Brunch",
            sort_order=30,
        )
        UploadCategoryTemplate.objects.create(
            event_type=brunch_type,
            code="welcome",
            label="Accueil",
            sort_order=1,
        )
        UploadCategoryTemplate.objects.create(
            event_type=brunch_type,
            code="toast",
            label="Toast",
            sort_order=2,
        )

        event = Event.objects.create(
            organizer=self.organizer,
            title="Brunch du lendemain",
            event_type=brunch_type,
            event_date=date(2026, 7, 9),
        )

        self.assertEqual(
            list(event.upload_categories.order_by("sort_order").values_list("code", flat=True)),
            ["welcome", "toast"],
        )

    def test_event_type_without_templates_uses_generic_templates(self):
        custom_type = EventType.objects.create(
            code="festival",
            label="Festival",
            sort_order=40,
        )

        event = Event.objects.create(
            organizer=self.organizer,
            title="Festival Memora",
            event_type=custom_type,
            event_date=date(2026, 7, 9),
        )

        self.assertEqual(event.upload_categories.order_by("sort_order").first().code, "arrival")
        self.assertTrue(event.upload_categories.filter(code="other").exists())


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

    def upload_url(self, event=None, access_key=None):
        event = event or self.event
        return reverse(
            "uploads:create",
            kwargs={
                "slug": event.slug,
                "access_key": access_key or event.public_access_key,
            },
        )

    def thanks_url(self, event=None, access_key=None):
        event = event or self.event
        return reverse(
            "uploads:thanks",
            kwargs={
                "slug": event.slug,
                "access_key": access_key or event.public_access_key,
            },
        )

    def test_guest_can_upload_memory_without_account(self):
        media = SimpleUploadedFile("photo.jpg", b"fake-image", content_type="image/jpeg")

        response = self.client.post(
            self.upload_url(),
            {
                "media_file": media,
                "category": self.category.pk,
            },
        )

        self.assertRedirects(response, self.thanks_url())
        upload = GuestUpload.objects.get(event=self.event)
        self.assertEqual(upload.media_type, GuestUpload.MediaType.IMAGE)
        self.assertEqual(upload.original_filename, "photo.jpg")
        self.assertEqual(upload.moderation_status, GuestUpload.ModerationStatus.APPROVED)
        self.assertTrue(upload.session_key)

    def test_guest_upload_requires_access_key(self):
        response_without_key = self.client.get(f"/e/{self.event.slug}/souvenir/")
        response_with_wrong_key = self.client.get(self.upload_url(access_key="mauvaise-cle"))

        self.assertEqual(response_without_key.status_code, 404)
        self.assertEqual(response_with_wrong_key.status_code, 404)

    def test_guest_upload_page_is_mobile_first(self):
        response = self.client.get(self.upload_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Prendre une photo ou filmer")
        self.assertContains(response, "Selfie, camera arriere, filtres")
        self.assertContains(response, "Camera Memora")
        self.assertContains(response, "Lancer la camera")
        self.assertContains(response, "Selfie")
        self.assertContains(response, "Arriere")
        self.assertContains(response, "REC")
        self.assertContains(response, "mode-toggle-button")
        self.assertContains(response, "camera-action-button")
        self.assertContains(response, "lens-toggle-button")
        self.assertNotContains(response, "photo-mode-button")
        self.assertNotContains(response, "video-mode-button")
        self.assertNotContains(response, "record-video-button")
        self.assertNotContains(response, "stop-video-button")
        self.assertContains(response, "Noir blanc")
        self.assertContains(response, "Photo")
        self.assertContains(response, "Video")
        self.assertContains(response, "Ouvrir l'appareil natif")
        self.assertContains(response, "Souvenir pret a envoyer")
        self.assertContains(response, "Reprendre avec la camera")
        self.assertContains(response, "Moment obligatoire")
        self.assertNotContains(response, "Choisir le moment")
        self.assertContains(response, "obligatoire")
        self.assertContains(response, ">Moment</option>")
        self.assertNotContains(response, f"{self.category.label} - {self.event.title}")
        self.assertContains(response, "moment-select")
        self.assertContains(response, "5 souvenirs maximum par appareil")
        self.assertContains(response, "Il vous reste 5 envois")
        self.assertContains(response, "Envoyer le souvenir")
        self.assertContains(response, "upload-progress.js")

    @override_settings(MEMORA_UPLOAD_COOLDOWN_SECONDS=0)
    def test_guest_upload_page_shows_remaining_upload_count(self):
        media = SimpleUploadedFile("photo.jpg", b"fake-image", content_type="image/jpeg")
        self.client.post(
            self.upload_url(),
            {
                "media_file": media,
                "category": self.category.pk,
            },
        )

        response = self.client.get(self.upload_url())

        self.assertContains(response, "5 souvenirs maximum par appareil")
        self.assertContains(response, "Il vous reste 4 envois")

    def test_guest_confirmation_page_promotes_next_actions(self):
        response = self.client.get(self.thanks_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Souvenir envoye.")
        self.assertContains(response, "Ajouter un autre souvenir")
        self.assertContains(response, "Retour a l'evenement")
        self.assertContains(response, "Vous pouvez fermer cette page")

    def test_guest_upload_requires_guest_access_code_when_enabled(self):
        self.event.guest_access_code = "AMOUR2026"
        self.event.save()
        media = SimpleUploadedFile("photo.jpg", b"fake-image", content_type="image/jpeg")

        response = self.client.post(
            self.upload_url(),
            {
                "media_file": media,
                "category": self.category.pk,
            },
        )

        self.assertRedirects(response, self.event.get_public_url())
        self.assertEqual(GuestUpload.objects.count(), 0)

        self.client.post(self.event.get_public_url(), {"guest_access_code": "amour2026"})
        unlocked_media = SimpleUploadedFile("photo.jpg", b"fake-image", content_type="image/jpeg")
        unlocked_response = self.client.post(
            self.upload_url(),
            {
                "media_file": unlocked_media,
                "category": self.category.pk,
            },
        )

        self.assertRedirects(unlocked_response, self.thanks_url())
        self.assertEqual(GuestUpload.objects.count(), 1)

    def test_rejects_invalid_file_extension(self):
        media = SimpleUploadedFile("notes.pdf", b"pdf", content_type="application/pdf")

        response = self.client.post(
            self.upload_url(),
            {
                "media_file": media,
                "category": self.category.pk,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ce format n&#x27;est pas accepte.")
        self.assertEqual(GuestUpload.objects.count(), 0)

    def test_rejects_invalid_content_type(self):
        media = SimpleUploadedFile("photo.jpg", b"not-an-image", content_type="text/plain")

        response = self.client.post(
            self.upload_url(),
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
            self.upload_url(),
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
            self.upload_url(),
            {
                "media_file": media,
                "category": self.category.pk,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Cette video est trop lourde.")
        self.assertEqual(GuestUpload.objects.count(), 0)

    @patch("uploads.forms._probe_video_duration", return_value=11)
    def test_rejects_video_longer_than_ten_seconds(self, _probe_video_duration):
        media = SimpleUploadedFile("video.mp4", b"video", content_type="video/mp4")

        response = self.client.post(
            self.upload_url(),
            {
                "media_file": media,
                "category": self.category.pk,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Cette video depasse 10 secondes.")
        self.assertEqual(GuestUpload.objects.count(), 0)

    @patch("uploads.forms._probe_video_duration", return_value=9.5)
    def test_stores_video_duration_when_upload_is_allowed(self, _probe_video_duration):
        media = SimpleUploadedFile("video.mp4", b"video", content_type="video/mp4")

        response = self.client.post(
            self.upload_url(),
            {
                "media_file": media,
                "category": self.category.pk,
            },
        )

        self.assertRedirects(response, self.thanks_url())
        upload = GuestUpload.objects.get(event=self.event)
        self.assertEqual(upload.media_type, GuestUpload.MediaType.VIDEO)
        self.assertEqual(upload.duration.total_seconds(), 9.5)

    @patch(
        "uploads.forms._probe_video_duration",
        side_effect=forms.ValidationError("La duree de cette video ne peut pas etre verifiee."),
    )
    def test_accepts_memora_camera_duration_when_ffprobe_cannot_read_video(self, _probe_video_duration):
        media = SimpleUploadedFile("video.webm", b"video", content_type="video/webm")

        response = self.client.post(
            self.upload_url(),
            {
                "media_file": media,
                "category": self.category.pk,
                "client_duration_seconds": "8.25",
            },
        )

        self.assertRedirects(response, self.thanks_url())
        upload = GuestUpload.objects.get(event=self.event)
        self.assertEqual(upload.media_type, GuestUpload.MediaType.VIDEO)
        self.assertEqual(upload.duration.total_seconds(), 8.25)

    @override_settings(MEMORA_MAX_UPLOAD_SIZE=50, MEMORA_CLIENT_DURATION_FALLBACK_MAX_SIZE=4)
    @patch(
        "uploads.forms._probe_video_duration",
        side_effect=forms.ValidationError("La duree de cette video ne peut pas etre verifiee."),
    )
    def test_rejects_client_duration_fallback_for_large_unreadable_video(self, _probe_video_duration):
        media = SimpleUploadedFile("video.webm", b"video", content_type="video/webm")

        response = self.client.post(
            self.upload_url(),
            {
                "media_file": media,
                "category": self.category.pk,
                "client_duration_seconds": "8.25",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "La duree de cette video ne peut pas etre verifiee.")
        self.assertEqual(GuestUpload.objects.count(), 0)

    @override_settings(MEMORA_SESSION_UPLOAD_LIMIT=1)
    def test_limits_uploads_by_session(self):
        first_media = SimpleUploadedFile("first.jpg", b"first", content_type="image/jpeg")
        second_media = SimpleUploadedFile("second.jpg", b"second", content_type="image/jpeg")

        self.client.post(
            self.upload_url(),
            {
                "media_file": first_media,
                "category": self.category.pk,
            },
        )
        response = self.client.post(
            self.upload_url(),
            {
                "media_file": second_media,
                "category": self.category.pk,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Vous avez atteint la limite de 1 souvenir")
        self.assertEqual(GuestUpload.objects.count(), 1)

    @override_settings(MEMORA_SESSION_UPLOAD_LIMIT=5, MEMORA_UPLOAD_COOLDOWN_SECONDS=0)
    def test_limits_guest_to_five_uploads_by_session(self):
        for index in range(5):
            media = SimpleUploadedFile(f"photo-{index}.jpg", b"fake-image", content_type="image/jpeg")
            response = self.client.post(
                self.upload_url(),
                {
                    "media_file": media,
                    "category": self.category.pk,
                },
            )
            self.assertRedirects(response, self.thanks_url())

        extra_media = SimpleUploadedFile("extra.jpg", b"fake-image", content_type="image/jpeg")
        response = self.client.post(
            self.upload_url(),
            {
                "media_file": extra_media,
                "category": self.category.pk,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Limite atteinte")
        self.assertEqual(GuestUpload.objects.count(), 5)

    @override_settings(MEMORA_UPLOAD_COOLDOWN_SECONDS=60)
    def test_limits_rapid_uploads_by_session_or_ip(self):
        first_media = SimpleUploadedFile("first.jpg", b"first", content_type="image/jpeg")
        second_media = SimpleUploadedFile("second.jpg", b"second", content_type="image/jpeg")

        self.client.post(
            self.upload_url(),
            {
                "media_file": first_media,
                "category": self.category.pk,
            },
        )
        response = self.client.post(
            self.upload_url(),
            {
                "media_file": second_media,
                "category": self.category.pk,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Patientez quelques secondes")
        self.assertEqual(GuestUpload.objects.count(), 1)
