from datetime import date
from io import BytesIO
import shutil
import tempfile
from unittest.mock import patch

from django import forms
from django.conf import settings
from django.core.cache import cache
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from core.storage_errors import STORAGE_UNAVAILABLE_MESSAGE
from events.models import Event, EventType

from .models import GuestUpload, MomentTemplate, UploadCategory, UploadCategoryTemplate
from .services import normalize_moment_label, sync_event_upload_categories

TEST_MEDIA_ROOT = tempfile.mkdtemp()

# Les videos sont verifiees sur leurs premiers octets (voir uploads.forms._looks_like_video).
MP4_HEAD = bytes([0, 0, 0, 24]) + b"ftypmp42" + bytes(16)
WEBM_HEAD = bytes([0x1A, 0x45, 0xDF, 0xA3]) + bytes(60)


def make_test_image_bytes(image_format="JPEG"):
    buffer = BytesIO()
    Image.new("RGB", (8, 8), color=(240, 80, 120)).save(buffer, format=image_format)
    return buffer.getvalue()


def make_test_image_file(filename="photo.jpg", content_type="image/jpeg", image_format="JPEG"):
    return SimpleUploadedFile(filename, make_test_image_bytes(image_format), content_type=content_type)


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
        self.assertEqual(second_event.upload_categories.get(code="ceremony").label, "Cérémonie")

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

    def test_known_moments_are_loaded_into_global_library(self):
        self.assertTrue(
            MomentTemplate.objects.filter(
                code="ceremony",
                label="Cérémonie",
                status=MomentTemplate.ModerationStatus.APPROVED,
            ).exists()
        )
        self.assertTrue(
            MomentTemplate.objects.filter(
                code="dancefloor",
                label="Piste de danse",
                status=MomentTemplate.ModerationStatus.APPROVED,
            ).exists()
        )

    def test_custom_moment_labels_are_normalized_for_better_ux(self):
        self.assertEqual(normalize_moment_label("  PHOTO   BOOTH  "), "Photo booth")

        event = Event.objects.create(
            organizer=self.organizer,
            title="Soiree normalisee",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
        )
        sync_event_upload_categories(
            event,
            ["new:  PHOTO   BOOTH  "],
            user=self.organizer,
            count_all_usage=True,
        )

        moment = MomentTemplate.objects.get(code="photo-booth")
        self.assertEqual(moment.label, "Photo booth")
        self.assertTrue(event.upload_categories.filter(code="photo-booth", label="Photo booth").exists())

    @override_settings(MEMORA_MOMENT_AUTO_PROMOTION_USAGE_THRESHOLD=2)
    def test_custom_moment_is_auto_promoted_after_repeated_usage(self):
        first_event = Event.objects.create(
            organizer=self.organizer,
            title="Premier photobooth",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
        )
        sync_event_upload_categories(
            first_event,
            ["new:Photo booth"],
            user=self.organizer,
            count_all_usage=True,
        )

        moment = MomentTemplate.objects.get(code="photo-booth")
        self.assertEqual(moment.status, MomentTemplate.ModerationStatus.PENDING)
        self.assertEqual(moment.usage_count, 1)

        second_event = Event.objects.create(
            organizer=self.organizer,
            title="Second photobooth",
            event_type=self.event_type,
            event_date=date(2026, 7, 9),
        )
        sync_event_upload_categories(
            second_event,
            ["new:Photo booth"],
            user=self.organizer,
            count_all_usage=True,
        )

        moment.refresh_from_db()
        self.assertEqual(moment.status, MomentTemplate.ModerationStatus.APPROVED)
        self.assertEqual(moment.usage_count, 2)
        self.assertIsNotNone(moment.auto_promoted_at)


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
        self.event.mark_paid(provider="test")
        self.event.save(update_fields=["payment_status", "paid_at", "payment_provider"])
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
        media = make_test_image_file("photo.jpg")

        response = self.client.post(
            self.upload_url(),
            {
                "media_file": media,
            },
        )

        self.assertRedirects(response, self.thanks_url())
        upload = GuestUpload.objects.get(event=self.event)
        self.assertEqual(upload.media_type, GuestUpload.MediaType.IMAGE)
        self.assertEqual(upload.original_filename, "photo.jpg")
        self.assertEqual(upload.moderation_status, GuestUpload.ModerationStatus.APPROVED)
        self.assertTrue(upload.session_key)

    def _post_photo(self, client, device_id="", name="p.jpg"):
        return client.post(self.upload_url(), {"media_file": make_test_image_file(name), "device_id": device_id, "device_sig": "abcdef0123456789"})

    @override_settings(MEMORA_UPLOAD_COOLDOWN_SECONDS=0, MEMORA_SESSION_UPLOAD_LIMIT=2)
    def test_clearing_cookies_does_not_reset_the_guest_limit(self):
        """Le compteur suit l'appareil, pas seulement le cookie de session : vider ses cookies (mais
        pas le stockage du navigateur) ou perdre la session ne redonne pas de souvenirs."""
        from django.test import Client

        device = "a" * 36
        first = Client()
        self.assertRedirects(self._post_photo(first, device), self.thanks_url())
        self.assertRedirects(self._post_photo(first, device), self.thanks_url())

        # Cookies vides = nouvelle session et nouveau cookie d'appareil, mais meme identifiant du navigateur.
        wiped = Client()
        response = self._post_photo(wiped, device)
        self.assertContains(response, "limite de 2 souvenirs")
        self.assertEqual(GuestUpload.objects.filter(event=self.event).count(), 2)

    @override_settings(MEMORA_UPLOAD_COOLDOWN_SECONDS=0, MEMORA_SESSION_UPLOAD_LIMIT=2)
    def test_losing_the_browser_id_is_caught_by_the_device_cookie(self):
        """Storage vide mais cookie serveur conserve : toujours reconnu."""
        from django.test import Client

        client = Client()
        self._post_photo(client, "b" * 36)
        self._post_photo(client, "b" * 36)
        client.cookies.pop("sessionid", None)  # session perdue, cookie d'appareil garde

        response = self._post_photo(client, "")
        self.assertContains(response, "limite de 2 souvenirs")

    @override_settings(MEMORA_UPLOAD_COOLDOWN_SECONDS=0, MEMORA_SESSION_UPLOAD_LIMIT=2)
    def test_another_guest_with_the_same_phone_model_is_never_blocked(self):
        """Deux telephones identiques partagent la meme empreinte materielle : l'empreinte est
        enregistree mais ne bloque jamais, pour ne pas priver un invite honnete."""
        from django.test import Client

        for _ in range(2):
            self._post_photo(Client(), "c" * 36 if _ == 0 else "d" * 36)
        for _ in range(2):
            self._post_photo(Client(), "e" * 36 if _ == 0 else "f" * 36)

        self.assertEqual(GuestUpload.objects.filter(event=self.event, device_signature="abcdef0123456789").count(), 4)

    @override_settings(MEMORA_UPLOAD_COOLDOWN_SECONDS=0, MEMORA_SESSION_UPLOAD_LIMIT=2)
    def test_junk_device_values_are_ignored(self):
        from django.test import Client

        client = Client()
        response = client.post(self.upload_url(), {"media_file": make_test_image_file("j.jpg"), "device_id": "<script>", "device_sig": "zz"})
        self.assertRedirects(response, self.thanks_url())
        upload = GuestUpload.objects.get(event=self.event)
        self.assertEqual(upload.device_id, "")
        self.assertEqual(upload.device_signature, "")

    def test_the_device_cookie_is_set_by_the_server_and_kept(self):
        response = self.client.get(self.upload_url())

        cookie = response.cookies["memora_device"]
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["max-age"], 60 * 60 * 24 * 365)
        second = self.client.get(self.upload_url())
        self.assertNotIn("memora_device", second.cookies)  # deja pose : on ne le change pas

    @patch("uploads.models.GuestUpload.save", side_effect=OSError("storage down"))
    def test_guest_upload_storage_error_returns_form_error(self, _upload_save):
        media = make_test_image_file("photo.jpg")

        response = self.client.post(
            self.upload_url(),
            {
                "media_file": media,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, STORAGE_UNAVAILABLE_MESSAGE)
        self.assertEqual(GuestUpload.objects.count(), 0)

    def test_guest_upload_requires_access_key(self):
        response_without_key = self.client.get(f"/e/{self.event.slug}/souvenir/")
        response_with_wrong_key = self.client.get(self.upload_url(access_key="mauvaise-cle"))

        self.assertEqual(response_without_key.status_code, 404)
        self.assertEqual(response_with_wrong_key.status_code, 404)

    def test_guest_upload_requires_paid_event(self):
        self.event.payment_status = Event.PaymentStatus.PENDING
        self.event.paid_at = None
        self.event.save(update_fields=["payment_status", "paid_at"])
        media = make_test_image_file("photo.jpg")

        response = self.client.post(
            self.upload_url(),
            {
                "media_file": media,
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "Événement pas encore activé", status_code=403)
        self.assertEqual(GuestUpload.objects.count(), 0)

    def test_guest_upload_page_is_mobile_first(self):
        response = self.client.get(self.upload_url())

        self.assertEqual(response.status_code, 200)
        # L'invite doit savoir a quel evenement il contribue.
        self.assertContains(response, self.event.title)
        self.assertNotContains(response, "Inscription")
        # Deux actions, rien d'autre : pas de jargon de marque ni de slogan.
        self.assertNotContains(response, "Capturez sans quitter la page")
        self.assertContains(response, "(10 s max)")
        self.assertContains(response, "start-camera-photo-button")
        self.assertContains(response, "start-camera-video-button")
        self.assertContains(response, "Selfie")
        self.assertContains(response, "REC")
        self.assertContains(response, "mode-toggle-button")
        self.assertContains(response, "camera-action-button")
        self.assertContains(response, "lens-toggle-button")
        self.assertNotContains(response, "photo-mode-button")
        self.assertNotContains(response, "video-mode-button")
        self.assertNotContains(response, "record-video-button")
        self.assertNotContains(response, "stop-video-button")
        self.assertNotContains(response, "Noir blanc")
        self.assertNotContains(response, "camera-filter")
        self.assertContains(response, "Photo")
        self.assertContains(response, "Vidéo")
        self.assertNotContains(response, "Caméra du téléphone")
        self.assertNotContains(response, "Ouvrir l'appareil natif")
        self.assertNotContains(response, "galerie")
        self.assertContains(response, "Souvenir prêt à envoyer")
        self.assertContains(response, "Reprendre")
        # La revue plein ecran envoie directement le souvenir : pas d'etape de confirmation intermediaire.
        self.assertNotContains(response, "Utiliser ce souvenir")
        self.assertNotContains(response, "Choisir un autre fichier")
        self.assertContains(response, "capture-preview-backdrop")
        # L'invite n'a plus a choisir un moment : le champ a disparu du formulaire.
        self.assertNotContains(response, "Moment obligatoire")
        self.assertNotContains(response, "Sélectionner le moment")
        self.assertNotContains(response, "moment-select")
        # Le plafond est annonce des l'arrivee, sans alarmer.
        self.assertContains(response, "Jusqu'à 5 souvenirs par invité")
        self.assertNotContains(response, "souvenirs maximum par appareil")
        self.assertNotContains(response, "Il vous reste")
        self.assertContains(response, "Envoyer le souvenir")
        self.assertContains(response, "upload-progress.js")
        # Un echec d'envoi (reseau, validation, stockage) doit pouvoir s'afficher
        # sans jamais recharger toute la page ni faire perdre la capture.
        self.assertContains(response, 'class="capture-preview__errors" hidden')

    def test_camera_javascript_covers_final_mobile_ux_states(self):
        script = (settings.BASE_DIR / "static" / "js" / "upload-progress.js").read_text(encoding="utf-8")

        self.assertIn("navigator.mediaDevices.getUserMedia", script)
        self.assertIn("navigator.permissions.query", script)
        self.assertIn("MediaRecorder", script)
        self.assertIn("facingMode", script)
        self.assertIn("Tournez le téléphone", self.client.get(self.upload_url()).content.decode())
        self.assertIn("Vidéo en cours - stop pour terminer", script)
        self.assertIn("Vidéo en préparation", script)
        self.assertIn("Connexion lente", script)
        self.assertIn("L'envoi a échoué", script)
        self.assertIn("capturePreview", script)
        # Un echec (reseau, validation, stockage) ne doit plus jamais recharger
        # toute la page : la revue reste ouverte et affiche le meme message.
        self.assertNotIn("document.write", script)
        self.assertIn("finishFailedSend", script)

    @override_settings(MEMORA_UPLOAD_COOLDOWN_SECONDS=0)
    def test_guest_upload_page_shows_remaining_upload_count(self):
        media = make_test_image_file("photo.jpg")
        self.client.post(
            self.upload_url(),
            {
                "media_file": media,
            },
        )

        response = self.client.get(self.upload_url())

        self.assertContains(response, "1 souvenir envoyé sur 5")
        self.assertNotContains(response, "Il vous reste")

    @override_settings(MEMORA_UPLOAD_COOLDOWN_SECONDS=0, MEMORA_SESSION_UPLOAD_LIMIT=4)
    def test_quota_text_and_dots_follow_the_uploads(self):
        first = self.client.get(self.upload_url())
        self.assertContains(first, "Jusqu'à 4 souvenirs par invité")
        self.assertContains(first, "<i></i><i></i><i></i><i></i>", html=False)
        self.assertNotContains(first, 'class="is-used"')

        self.client.post(self.upload_url(), {"media_file": make_test_image_file("un.jpg")})
        one = self.client.get(self.upload_url())
        self.assertContains(one, "1 souvenir envoyé sur 4")
        self.assertContains(one, '<i class="is-used"></i><i></i><i></i><i></i>')
        # « Terminer » n'apparait qu'une fois un souvenir envoye.
        self.assertRegex(first.content.decode(), r'id="upload-quota-finish" href="[^"]+" hidden')
        self.assertNotRegex(one.content.decode(), r'id="upload-quota-finish" href="[^"]+" hidden')

        self.client.post(self.upload_url(), {"media_file": make_test_image_file("deux.jpg")})
        self.assertContains(self.client.get(self.upload_url()), "Plus que 2 envois")

        self.client.post(self.upload_url(), {"media_file": make_test_image_file("trois.jpg")})
        self.assertContains(self.client.get(self.upload_url()), "Plus qu'un envoi")

    @override_settings(MEMORA_SESSION_UPLOAD_LIMIT=12)
    def test_quota_dots_are_left_out_when_the_limit_is_large(self):
        response = self.client.get(self.upload_url())

        self.assertContains(response, "Jusqu'à 12 souvenirs par invité")
        self.assertNotContains(response, "upload-quota-dots")

    def test_camera_panel_ships_hidden_and_the_stylesheet_lets_hidden_win(self):
        """`.camera-panel { display: grid }` battait l'attribut hidden : le viseur
        noir et ses commandes s'affichaient des l'arrivee de l'invite."""
        response = self.client.get(self.upload_url())
        css = (settings.BASE_DIR / "static" / "css" / "base.css").read_text(encoding="utf-8")

        self.assertContains(response, 'id="camera-panel" role="dialog" aria-modal="true" aria-label="Caméra Memora" hidden')
        self.assertIn(".camera-panel[hidden]", css)

    def test_native_photo_fallback_opens_the_phone_camera_for_photos_only(self):
        response = self.client.get(self.upload_url())
        html = response.content.decode()
        input_tag = html[html.index('id="native-photo-input"') - 40:html.index('id="native-photo-input"') + 120]

        self.assertContains(response, "native-photo-button")
        self.assertContains(response, "native-photo.js")
        # Photo uniquement, prise sur le moment : ni video, ni galerie.
        self.assertIn('accept="image/*"', input_tag)
        self.assertIn('capture="environment"', input_tag)
        self.assertNotIn("video", input_tag)
        # Cet input n'a pas de nom : il n'est jamais poste tel quel.
        self.assertNotIn('name="', input_tag)
        # Le champ principal (1er input fichier) reste celui que upload-progress.js pilote.
        self.assertLess(html.index('name="media_file"'), html.index('id="native-photo-input"'))

    @override_settings(MEMORA_SESSION_UPLOAD_LIMIT=0)
    def test_native_photo_fallback_is_hidden_once_the_limit_is_reached(self):
        self.assertNotContains(self.client.get(self.upload_url()), "native-photo-button")

    def test_guest_pages_have_no_marketing_footer(self):
        for url in (self.upload_url(), self.thanks_url()):
            response = self.client.get(url)

            self.assertNotContains(response, "site-footer")
            self.assertNotContains(response, "Programme Ambassadeur")
            self.assertNotContains(response, "Créer un événement")

    def test_filters_are_gone_from_the_camera_script(self):
        script = (settings.BASE_DIR / "static" / "js" / "upload-progress.js").read_text(encoding="utf-8")

        self.assertNotIn("cameraFilters", script)
        self.assertNotIn("data-camera-filter", script)

    def test_form_exposes_what_the_script_needs_to_stay_in_the_camera(self):
        response = self.client.get(self.upload_url())
        html = response.content.decode()

        self.assertContains(response, 'data-remaining="5"')
        self.assertContains(response, f'data-thanks-url="{self.thanks_url()}"')
        self.assertIn('id="upload-quota" data-limit="5"', html)
        # Le lien « Terminer » existe mais reste cache tant que rien n'est parti.
        self.assertIn('id="upload-quota-finish"', html)
        self.assertRegex(html, r'id="upload-quota-finish" href="[^"]+" hidden')
        self.assertContains(response, 'id="camera-sent-count"')

    def test_camera_script_keeps_the_guest_in_the_camera_between_sends(self):
        script = (settings.BASE_DIR / "static" / "js" / "upload-progress.js").read_text(encoding="utf-8")
        css = (settings.BASE_DIR / "static" / "css" / "base.css").read_text(encoding="utf-8")

        self.assertIn("finishSuccessfulSend", script)
        self.assertIn("Envoyé ✓", script)
        # Le cercle de compte a rebours suit l'enregistrement de la video.
        self.assertIn("--rec-progress", script)
        self.assertIn("--rec-progress", css)
        # Les blocs caches par attribut doivent vraiment disparaitre.
        self.assertIn(".upload-quota a[hidden]", css)

    def test_recording_asks_safari_for_mp4_and_explains_an_unreadable_preview(self):
        """Safari (iOS 18.4+) enregistre en WebM/VP9 mais ne le relit pas toujours :
        apercu noir avec « Video prete - 11,2 Mo » et aucune duree. On lui demande du
        MP4, et si l'apercu reste illisible on le dit au lieu de laisser croire a un bug."""
        for name in ("upload-progress.js", "guestbook-capture.js"):
            script = (settings.BASE_DIR / "static" / "js" / name).read_text(encoding="utf-8")

            self.assertIn("prefersMp4Recording", script, name)
            self.assertIn("video/mp4;codecs=avc1.42E01E,mp4a.40.2", script, name)
            self.assertIn("iP(hone|ad|od)", script, name)
            self.assertIn("explainUnreadablePreview", script, name)
            self.assertIn("Aperçu animé indisponible sur cet appareil" if name == "upload-progress.js" else "Aperçu indisponible sur cet appareil", script, name)

    def test_guest_video_preview_never_shows_a_black_screen(self):
        """Affiche = derniere image du viseur ; lecture relancee une fois la revue affichee ;
        commandes natives si l'autoplay est refuse ; un toucher active le son."""
        script = (settings.BASE_DIR / "static" / "js" / "upload-progress.js").read_text(encoding="utf-8")

        for fragment in ("captureLiveFrame", "previewVideo.poster", "retryPreviewPlayback", "previewVideo.controls = true", "retryWithPlainType", "reportPreviewProblem"):
            self.assertIn(fragment, script, fragment)

    def test_the_first_visit_guide_is_offered_but_never_blocks_the_guest_page(self):
        """Guide de premiere visite : 3 ecrans caches par defaut (aucun blocage sans JavaScript), rouvrable
        par un lien, et absent quand la limite est atteinte. Aucun mot sur le film ni sur Memora."""
        response = self.client.get(self.upload_url())

        self.assertContains(response, 'id="guide"')
        self.assertContains(response, 'data-guide-key="guest-v1"')
        self.assertContains(response, "data-guide-open")
        self.assertContains(response, "Acceptez la caméra et le micro")
        html = response.content.decode()
        guide_html = html.split('id="guide"')[1].split("guide__footer")[0].lower()
        for forbidden in ("film", "montage", "galerie", "memora"):
            self.assertNotIn(forbidden.replace("film", "film "), guide_html, forbidden)
        self.assertIn("hidden>", html.split('id="guide"')[1][:260])  # ferme tant que le script ne l'ouvre pas
        script = (settings.BASE_DIR / "static" / "js" / "guide.js").read_text(encoding="utf-8")
        for fragment in ("localStorage", "Escape", "camera-open", "memora_guide_"):
            self.assertIn(fragment, script, fragment)

    @override_settings(MEMORA_SESSION_UPLOAD_LIMIT=1, MEMORA_UPLOAD_COOLDOWN_SECONDS=0)
    def test_no_guide_once_the_guest_limit_is_reached(self):
        self.client.post(self.upload_url(), {"media_file": make_test_image_file("g.jpg")})

        response = self.client.get(self.upload_url())

        self.assertNotContains(response, 'id="guide"')

    def test_flash_button_is_wired_on_both_camera_screens(self):
        """Le bouton flash n'existe que si le telephone confirme une torche pilotable (camera arriere
        avec flash) : cache par defaut dans le gabarit, revele via getCapabilities().torch, jamais
        propose en selfie. La demande de camera ne doit jamais echouer a cause d'un flash absent."""
        for js_name, html_name in (
            ("upload-progress.js", "uploads/guest_upload_form.html"),
            ("guestbook-capture.js", "guestbook/capture.html"),
        ):
            script = (settings.BASE_DIR / "static" / "js" / js_name).read_text(encoding="utf-8")
            template = (settings.BASE_DIR / "templates" / html_name).read_text(encoding="utf-8")

            self.assertIn('id="flash-toggle-button"', template, html_name)
            self.assertIn("hidden>", template.split('id="flash-toggle-button"')[1][:120], html_name)
            for fragment in ("getCapabilities", "torch", "applyConstraints", "detectFlashSupport", "flashSupported"):
                self.assertIn(fragment, script, f"{js_name}: {fragment}")

        css = (settings.BASE_DIR / "static" / "css" / "base.css").read_text(encoding="utf-8")
        self.assertIn(".camera-flash-button", css)

    def test_cover_photo_is_framed_towards_the_top_so_faces_are_not_cut(self):
        css = (settings.BASE_DIR / "static" / "css" / "base.css").read_text(encoding="utf-8")

        self.assertIn(".guest-upload-heading--hero .guest-upload-heading__cover", css)
        self.assertIn("object-position: 50% 18%", css)

    def test_guest_confirmation_page_has_a_single_next_action(self):
        response = self.client.get(self.thanks_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Souvenir envoyé.")
        self.assertContains(response, "Envoyer un autre souvenir")
        # « Retour a l'evenement » menait a la meme page d'envoi : un seul bouton.
        self.assertNotContains(response, "Retour à l")
        # Les films sont pour l'organisateur : l'invite envoie des souvenirs, point.
        self.assertNotContains(response, "film souvenir sera")
        self.assertNotContains(response, "Voir le film")
        self.assertContains(response, "Vous pouvez fermer cette page")

    def test_guest_upload_requires_guest_access_code_when_enabled(self):
        self.event.guest_access_code = "AMOUR2026"
        self.event.save()
        media = make_test_image_file("photo.jpg")

        response = self.client.post(
            self.upload_url(),
            {
                "media_file": media,
            },
        )

        self.assertRedirects(response, self.event.get_public_url())
        self.assertEqual(GuestUpload.objects.count(), 0)

        self.client.post(self.event.get_public_url(), {"guest_access_code": "amour2026"})
        unlocked_media = make_test_image_file("photo.jpg")
        unlocked_response = self.client.post(
            self.upload_url(),
            {
                "media_file": unlocked_media,
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
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ce format n&#x27;est pas")
        self.assertEqual(GuestUpload.objects.count(), 0)

    def test_rejects_invalid_content_type(self):
        media = SimpleUploadedFile("photo.jpg", b"not-an-image", content_type="text/plain")

        response = self.client.post(
            self.upload_url(),
            {
                "media_file": media,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ce format n&#x27;est pas accepté.")
        self.assertEqual(GuestUpload.objects.count(), 0)

    def test_rejects_invalid_image_payload_even_with_image_content_type(self):
        media = SimpleUploadedFile("photo.jpg", b"not-an-image", content_type="image/jpeg")

        response = self.client.post(
            self.upload_url(),
            {
                "media_file": media,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ce format n&#x27;est pas")
        self.assertEqual(GuestUpload.objects.count(), 0)

    def test_guest_upload_gets_default_category_automatically(self):
        media = make_test_image_file("photo.jpg")

        response = self.client.post(
            self.upload_url(),
            {"media_file": media},
        )

        self.assertRedirects(response, self.thanks_url())
        upload = GuestUpload.objects.get(event=self.event)
        self.assertEqual(upload.category.code, "other")
        self.assertEqual(upload.category.event_id, self.event.pk)

    def test_guest_upload_ignores_client_supplied_category(self):
        other_event = Event.objects.create(
            organizer=self.event.organizer,
            title="Autre mariage",
            event_type=self.event_type,
            event_date=date(2026, 7, 9),
        )
        other_category = other_event.upload_categories.get(code="ceremony")
        media = make_test_image_file("photo.jpg")

        response = self.client.post(
            self.upload_url(),
            {
                "media_file": media,
                "category": other_category.pk,
            },
        )

        self.assertRedirects(response, self.thanks_url())
        upload = GuestUpload.objects.get(event=self.event)
        self.assertEqual(upload.category.code, "other")
        self.assertNotEqual(upload.category_id, other_category.pk)

    @override_settings(MEMORA_MAX_UPLOAD_SIZE=4)
    def test_rejects_oversized_file(self):
        media = SimpleUploadedFile("video.mp4", MP4_HEAD + b"12345", content_type="video/mp4")

        response = self.client.post(
            self.upload_url(),
            {
                "media_file": media,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Cette vidéo est trop lourde.")
        self.assertEqual(GuestUpload.objects.count(), 0)

    @patch("uploads.forms._probe_video_duration", return_value=10.3)
    def test_a_video_recorded_to_the_automatic_stop_is_accepted(self, _probe_video_duration):
        """Un telephone qui coupe l'enregistrement a 10 s pile produit 10,0x a 10,3 s : refuser
        cet envoi APRES 10 Mo montes serait une mauvaise surprise pour l'invite."""
        media = SimpleUploadedFile("video.mp4", MP4_HEAD + b"video", content_type="video/mp4")

        response = self.client.post(self.upload_url(), {"media_file": media})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(GuestUpload.objects.count(), 1)

    @patch("uploads.forms._probe_video_duration", return_value=12)
    def test_rejects_video_longer_than_ten_seconds(self, _probe_video_duration):
        media = SimpleUploadedFile("video.mp4", MP4_HEAD + b"video", content_type="video/mp4")

        response = self.client.post(
            self.upload_url(),
            {
                "media_file": media,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Cette vidéo dépasse 10 secondes.")
        self.assertEqual(GuestUpload.objects.count(), 0)

    @patch("uploads.forms._probe_video_duration", return_value=9.5)
    def test_stores_video_duration_when_upload_is_allowed(self, _probe_video_duration):
        media = SimpleUploadedFile("video.mp4", MP4_HEAD + b"video", content_type="video/mp4")

        response = self.client.post(
            self.upload_url(),
            {
                "media_file": media,
            },
        )

        self.assertRedirects(response, self.thanks_url())
        upload = GuestUpload.objects.get(event=self.event)
        self.assertEqual(upload.media_type, GuestUpload.MediaType.VIDEO)
        self.assertEqual(upload.duration.total_seconds(), 9.5)

    @patch(
        "uploads.forms._probe_video_duration",
        side_effect=forms.ValidationError("La durée de cette vidéo ne peut pas être vérifiée."),
    )
    def test_accepts_memora_camera_duration_when_ffprobe_cannot_read_video(self, _probe_video_duration):
        media = SimpleUploadedFile("video.webm", WEBM_HEAD + b"video", content_type="video/webm")

        response = self.client.post(
            self.upload_url(),
            {
                "media_file": media,
                "client_duration_seconds": "8.25",
            },
        )

        self.assertRedirects(response, self.thanks_url())
        upload = GuestUpload.objects.get(event=self.event)
        self.assertEqual(upload.media_type, GuestUpload.MediaType.VIDEO)
        self.assertEqual(upload.duration.total_seconds(), 8.25)

    @override_settings(MEMORA_MAX_UPLOAD_SIZE=200, MEMORA_CLIENT_DURATION_FALLBACK_MAX_SIZE=4)
    @patch(
        "uploads.forms._probe_video_duration",
        side_effect=forms.ValidationError("La durée de cette vidéo ne peut pas être vérifiée."),
    )
    def test_rejects_client_duration_fallback_for_large_unreadable_video(self, _probe_video_duration):
        media = SimpleUploadedFile("video.webm", WEBM_HEAD + b"video", content_type="video/webm")

        response = self.client.post(
            self.upload_url(),
            {
                "media_file": media,
                "client_duration_seconds": "8.25",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "La durée de cette vidéo ne peut pas être vérifiée.")
        self.assertEqual(GuestUpload.objects.count(), 0)

    @override_settings(MEMORA_SESSION_UPLOAD_LIMIT=1)
    def test_limits_uploads_by_session(self):
        first_media = make_test_image_file("first.jpg")
        second_media = make_test_image_file("second.jpg")

        self.client.post(
            self.upload_url(),
            {
                "media_file": first_media,
            },
        )
        response = self.client.post(
            self.upload_url(),
            {
                "media_file": second_media,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Vous avez atteint la limite de 1 souvenir")
        self.assertEqual(GuestUpload.objects.count(), 1)

    @override_settings(MEMORA_SESSION_UPLOAD_LIMIT=5, MEMORA_UPLOAD_COOLDOWN_SECONDS=0)
    def test_limits_guest_to_five_uploads_by_session(self):
        for index in range(5):
            media = make_test_image_file(f"photo-{index}.jpg")
            response = self.client.post(
                self.upload_url(),
                {
                    "media_file": media,
                    },
            )
            self.assertRedirects(response, self.thanks_url())

        extra_media = make_test_image_file("extra.jpg")
        response = self.client.post(
            self.upload_url(),
            {
                "media_file": extra_media,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Limite atteinte")
        self.assertEqual(GuestUpload.objects.count(), 5)

        # Une fois la limite atteinte, l'invite ne doit plus pouvoir ouvrir la
        # camera pour rien : aucun chemin de capture ne peut aboutir.
        page_after_limit = self.client.get(self.upload_url())
        self.assertContains(page_after_limit, "Limite de souvenirs atteinte.")
        self.assertNotContains(page_after_limit, "start-camera-photo-button")
        self.assertNotContains(page_after_limit, "start-camera-video-button")

    @override_settings(MEMORA_UPLOAD_COOLDOWN_SECONDS=60)
    def test_limits_rapid_uploads_by_session_or_ip(self):
        first_media = make_test_image_file("first.jpg")
        second_media = make_test_image_file("second.jpg")

        self.client.post(
            self.upload_url(),
            {
                "media_file": first_media,
            },
        )
        response = self.client.post(
            self.upload_url(),
            {
                "media_file": second_media,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Patientez quelques secondes")
        self.assertEqual(GuestUpload.objects.count(), 1)


class ReviewScreenStylesTests(TestCase):
    """Garde-fou CSS : l'apercu video ne doit plus jamais etre repousse hors ecran."""

    def test_hidden_review_media_really_disappear(self):
        css = (settings.BASE_DIR / "static" / "css" / "base.css").read_text(encoding="utf-8")

        # « display: block » sur ces elements l'emportait sur l'attribut hidden : l'image vide
        # gardait sa place et repoussait la video -> apercu noir sur tous les navigateurs.
        self.assertIn("#capture-preview-image[hidden],\n#capture-preview-video[hidden] {\n  display: none;", css)


class PreviewDiagnosticTests(TestCase):
    """Rapport technique envoye par un telephone qui ne relit pas son enregistrement."""

    def setUp(self):
        cache.clear()  # la limite par adresse vit dans le cache
        organizer = get_user_model().objects.create_user(username="orga-diag", password="secret")
        self.event = Event.objects.create(
            organizer=organizer,
            title="Diagnostic",
            event_type=EventType.objects.get(code="wedding"),
            event_date=date(2026, 7, 8),
        )
        self.url = reverse("uploads:preview_diagnostic", kwargs={"slug": self.event.slug, "access_key": self.event.public_access_key})

    def test_report_is_logged_without_a_response_body(self):
        with self.assertLogs("uploads.views", level="WARNING") as logs:
            response = self.client.post(self.url, {"report": '{"stage": "error", "videoError": "4:"}'})

        self.assertEqual(response.status_code, 204)
        self.assertIn('"videoError": "4:"', logs.output[0])

    def test_reports_are_limited_per_address(self):
        with self.assertLogs("uploads.views", level="WARNING") as logs:
            for _ in range(15):
                self.client.post(self.url, {"report": "x"})

        self.assertEqual(len(logs.output), 10)

    def test_only_post_and_only_the_right_key(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        wrong = reverse("uploads:preview_diagnostic", kwargs={"slug": self.event.slug, "access_key": "mauvaise-cle"})
        self.assertEqual(self.client.post(wrong, {"report": "x"}).status_code, 404)

    def test_form_points_the_script_at_the_diagnostic_url(self):
        self.event.mark_paid(provider="test")
        self.event.event_date = timezone.localdate()
        self.event.save()
        create_url = reverse("uploads:create", kwargs={"slug": self.event.slug, "access_key": self.event.public_access_key})

        self.assertContains(self.client.get(create_url), f'data-diagnostic-url="{self.url}"')
