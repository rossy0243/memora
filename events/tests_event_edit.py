"""Modifier un evenement qui a deja une couverture et une musique : rien a renvoyer."""
import io
import shutil
import struct
import tempfile
import wave
from datetime import date

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from .models import Event, EventPlan, EventType

TEST_MEDIA_ROOT = tempfile.mkdtemp()


def jpeg():
    buffer = io.BytesIO()
    Image.new("RGB", (800, 500), (30, 120, 200)).save(buffer, format="JPEG")
    return buffer.getvalue()


def wav():
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(22050)
        handle.writeframes(b"".join(struct.pack("<h", 2000 if (i // 40) % 2 else -2000) for i in range(22050 * 2)))
    return buffer.getvalue()


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class EventEditTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        get_user_model().objects.create_user(username="orga-edit", password="secret", email="orga-edit@example.org")
        self.client.login(username="orga-edit", password="secret")
        self.plan = EventPlan.objects.filter(is_active=True, requires_quote=False).first()
        self.data = {
            "title": "Mariage a modifier", "couple_name": "Lea & Sam", "event_type": EventType.objects.get(code="wedding").pk,
            "plan": self.plan.pk, "event_date": date(2026, 9, 26).isoformat(), "welcome_message": "Bienvenue",
        }
        response = self.client.post(
            reverse("events:create"),
            {**self.data, "cover_image": SimpleUploadedFile("cover.jpg", jpeg(), content_type="image/jpeg"),
             "custom_music_file": SimpleUploadedFile("musique.wav", wav(), content_type="audio/wav")},
        )
        self.assertEqual(response.status_code, 302)
        self.event = Event.objects.get(title="Mariage a modifier")
        self.assertTrue(self.event.cover_image)
        self.assertTrue(self.event.custom_music_file)
        self.update_url = reverse("events:update", kwargs={"pk": self.event.pk})

    def test_editing_without_resending_the_files_keeps_them(self):
        """Regression : la couverture deja enregistree etait rejetee (« format non accepte ») a chaque modification."""
        cover, music = self.event.cover_image.name, self.event.custom_music_file.name

        response = self.client.post(self.update_url, {**self.data, "welcome_message": "Nouveau message d'accueil"})

        self.assertEqual(response.status_code, 302, getattr(response, "context", None) and response.context["form"].errors)
        self.event.refresh_from_db()
        self.assertEqual(self.event.welcome_message, "Nouveau message d'accueil")
        self.assertEqual((self.event.cover_image.name, self.event.custom_music_file.name), (cover, music))

    def test_a_new_cover_still_replaces_the_old_one_and_is_still_checked(self):
        old = self.event.cover_image.name

        ok = self.client.post(self.update_url, {**self.data, "cover_image": SimpleUploadedFile("nouvelle.jpg", jpeg(), content_type="image/jpeg")})
        self.assertEqual(ok.status_code, 302)
        self.event.refresh_from_db()
        self.assertNotEqual(self.event.cover_image.name, old)

        bad = self.client.post(self.update_url, {**self.data, "cover_image": SimpleUploadedFile("faux.jpg", b"pas une image", content_type="image/jpeg")})
        self.assertEqual(bad.status_code, 200)
        self.assertIn("cover_image", bad.context["form"].errors)
