from datetime import date
from io import BytesIO
import shutil
import tempfile
from unittest.mock import patch
from zipfile import ZipFile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from core.storage_errors import STORAGE_UNAVAILABLE_MESSAGE
from processing.models import GeneratedMovie
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
                "guest_access_code": "amour2026",
                "is_active": "on",
                "media_retention_days": "90",
            },
        )

        event = Event.objects.get(title="Mariage de Lea et Sam")
        self.assertRedirects(response, reverse("events:detail", kwargs={"pk": event.pk}))
        self.assertEqual(event.organizer, self.user)
        self.assertEqual(event.slug, "mariage-de-lea-et-sam")
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
        self.assertContains(response, "Collecte active")
        self.assertContains(response, "data-custom-event-type-field")
        self.assertContains(response, "data-custom-event-type-field hidden")
        self.assertContains(response, "event-form")
        self.assertNotContains(response, "Lieu (optionnel)")
        self.assertNotContains(response, "Conservation des médias")
        self.assertNotContains(response, "Couple name")

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

        response = self.client.get(event.get_public_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Lea &amp; Sam")
        self.assertContains(response, "Bienvenue dans nos souvenirs.")

    def test_public_event_with_guest_access_code_requires_session_validation(self):
        event = Event.objects.create(
            organizer=self.user,
            title="Reception code",
            couple_name="Lea & Sam",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
            guest_access_code="AMOUR2026",
        )

        response = self.client.get(event.get_public_url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Entrez le code invite.")
        self.assertNotContains(response, "Ajouter un souvenir")

        wrong_response = self.client.post(event.get_public_url(), {"guest_access_code": "NON"})
        self.assertEqual(wrong_response.status_code, 200)
        self.assertContains(wrong_response, "Code incorrect.")

        valid_response = self.client.post(event.get_public_url(), {"guest_access_code": "amour2026"})
        self.assertRedirects(valid_response, event.get_public_url())

        unlocked_response = self.client.get(event.get_public_url())
        self.assertContains(unlocked_response, "Ajouter un souvenir")

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
        self.assertContains(response, "Acces invite")
        self.assertContains(response, "Suivi en direct")
        self.assertContains(response, "Collecte active")
        self.assertContains(response, "Lien public et QR code")
        self.assertContains(response, "QR code et lien")
        self.assertContains(response, "Lien secret")
        self.assertContains(response, "AMOUR2026")
        self.assertContains(response, event.public_access_key)
        self.assertContains(response, "Medias invites")
        self.assertContains(response, "Derniers souvenirs")
        self.assertContains(response, "photo.jpg")
        self.assertContains(response, "video.mp4")
        self.assertNotContains(response, "deleted.jpg")
        self.assertEqual(response.context["media_stats"]["total"], 2)
        self.assertEqual(response.context["media_stats"]["photos"], 1)
        self.assertEqual(response.context["media_stats"]["videos"], 1)
        self.assertEqual(response.context["media_stats"]["selected_for_movie"], 1)

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

        self.assertContains(response, "Video automatique")
        self.assertContains(response, "Telecharger la video")
        self.assertContains(response, "100%")

    def test_event_detail_displays_automatic_movie_schedule(self):
        event = Event.objects.create(
            organizer=self.user,
            title="Reception Film Programme",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
        )
        self.client.login(username="owner", password="secret")

        response = self.client.get(reverse("events:detail", kwargs={"pk": event.pk}))

        self.assertContains(response, "Generation automatique prevue le 09/07/2026 a 12:00")
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
            progress_message="Assemblage des clips selectionnes.",
        )
        self.client.login(username="owner", password="secret")

        response = self.client.get(reverse("events:movie_status", kwargs={"pk": event.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "68%")
        self.assertContains(response, "Assemblage des clips selectionnes.")

    @patch("events.views.create_event_movie_job")
    def test_owner_can_generate_event_movie(self, create_event_movie_job):
        event = Event.objects.create(
            organizer=self.user,
            title="Reception Film Auto",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
        )
        create_event_movie_job.return_value = GeneratedMovie.objects.create(event=event)
        self.client.login(username="owner", password="secret")

        response = self.client.post(reverse("events:generate_movie", kwargs={"pk": event.pk}))

        self.assertRedirects(response, reverse("events:detail", kwargs={"pk": event.pk}))
        create_event_movie_job.assert_called_once_with(event)

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
        self.assertContains(response, "Voir tous les medias")

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
                .order_by("-uploaded_at")
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
            self.assertFalse(any("rejected" in name for name in names))

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
