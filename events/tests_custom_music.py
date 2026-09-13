"""Musique personnalisee televersee par l'organisateur : remplace le choix
automatique, sous reserve de disposer des droits (voir CGU)."""
from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Event, EventType


class CustomMusicUploadTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="owner-music", email="owner-music@example.com", password="secret"
        )
        self.event_type = EventType.objects.get(code="wedding")
        self.client.login(username="owner-music", password="secret")

    def _post(self, **extra):
        data = {
            "title": "Mariage musique perso",
            "couple_name": "Lea & Sam",
            "event_type": self.event_type.pk,
            "event_date": "2026-07-08",
            "welcome_message": "",
            "guest_access_code": "",
        }
        data.update(extra)
        return self.client.post(reverse("events:create"), data)

    @patch("processing.tempo.measure_tempo", return_value=(118.0, 0.2))
    @patch("events.forms.probe_video_duration", return_value=180.0)
    def test_valid_music_file_is_accepted_and_tempo_measured(self, _probe, _measure_tempo):
        music = SimpleUploadedFile("ma-chanson.mp3", b"fake-audio-bytes", content_type="audio/mpeg")

        response = self._post(custom_music_file=music)

        event = Event.objects.get(title="Mariage musique perso")
        self.assertRedirects(response, reverse("events:detail", kwargs={"pk": event.pk}))
        self.assertTrue(event.custom_music_file)
        self.assertEqual(event.custom_music_bpm, 118.0)
        self.assertEqual(event.custom_music_first_beat_offset, 0.2)

    def test_rejects_unsupported_format(self):
        music = SimpleUploadedFile("notice.txt", b"pas de la musique", content_type="text/plain")

        response = self._post(custom_music_file=music)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ce format audio n&#x27;est pas accepté.")
        self.assertFalse(Event.objects.filter(title="Mariage musique perso").exists())

    @override_settings(MEMORA_MAX_CUSTOM_MUSIC_SIZE=10)
    def test_rejects_oversized_file(self):
        music = SimpleUploadedFile("chanson.mp3", b"0123456789bytes-de-trop", content_type="audio/mpeg")

        response = self._post(custom_music_file=music)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "trop lourd")
        self.assertFalse(Event.objects.filter(title="Mariage musique perso").exists())

    @patch("events.forms.probe_video_duration", return_value=900.0)
    def test_rejects_too_long_track(self, _probe):
        music = SimpleUploadedFile("longue.mp3", b"fake-audio-bytes", content_type="audio/mpeg")

        response = self._post(custom_music_file=music)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "trop long")
        self.assertFalse(Event.objects.filter(title="Mariage musique perso").exists())

    def test_music_field_is_optional(self):
        response = self._post()

        self.assertRedirects(
            response,
            reverse("events:detail", kwargs={"pk": Event.objects.get(title="Mariage musique perso").pk}),
        )


class MeasureCustomMusicTempoTests(TestCase):
    def setUp(self):
        organizer = get_user_model().objects.create_user(username="orga-tempo", password="secret")
        self.event = Event.objects.create(
            organizer=organizer,
            title="Mariage Tempo",
            event_type=EventType.objects.get(code="wedding"),
            event_date=date(2026, 7, 8),
            custom_music_file=SimpleUploadedFile("piste.mp3", b"fake-audio-bytes"),
        )

    @patch("processing.tempo.measure_tempo", return_value=(128.5, 0.33))
    def test_measures_and_stores_tempo(self, _measure_tempo):
        result = self.event.measure_custom_music_tempo()

        self.assertTrue(result)
        self.event.refresh_from_db()
        self.assertEqual(self.event.custom_music_bpm, 128.5)
        self.assertEqual(self.event.custom_music_first_beat_offset, 0.33)

    @patch("processing.tempo.measure_tempo", side_effect=RuntimeError("ffmpeg indisponible"))
    def test_failure_is_best_effort(self, _measure_tempo):
        result = self.event.measure_custom_music_tempo()

        self.assertFalse(result)
        self.event.refresh_from_db()
        self.assertIsNone(self.event.custom_music_bpm)

    def test_without_file_does_nothing(self):
        self.event.custom_music_file = None
        self.assertFalse(self.event.measure_custom_music_tempo())
