from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import AgentProfile
from events.models import Event, EventType

from .models import GuestBookAssignment, GuestBookMessage, GuestBookMovie
from .services import queue_abandoned_guestbook_movies


def _write_montage_files(output_path, light_output_path=None, *, with_light=True):
    from processing.guestbook_montage import MontageResult

    Path(output_path).write_bytes(b"fake-hd-bytes")
    light = None
    if light_output_path and with_light:
        Path(light_output_path).write_bytes(b"fake-light")
        light = Path(light_output_path)
    return MontageResult(Path(output_path), light, 42.0)


def _fake_render(with_light=True):
    def fake_render(event, messages, output_path, light_output_path=None, progress_callback=None):
        return _write_montage_files(output_path, light_output_path, with_light=with_light)

    return fake_render


class GuestbookViewTests(TestCase):
    def setUp(self):
        self.agent = get_user_model().objects.create_user(username="agent1", password="secret")
        AgentProfile.objects.create(user=self.agent)
        self.other_agent = get_user_model().objects.create_user(username="agent2", password="secret")
        AgentProfile.objects.create(user=self.other_agent)
        self.organizer = get_user_model().objects.create_user(username="organizer", password="secret")
        self.event_type = EventType.objects.get(code="wedding")
        self.event = Event.objects.create(
            organizer=self.organizer,
            title="Mariage Livre d'Or",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
        )
        self.assignment = GuestBookAssignment.objects.create(event=self.event, agent=self.agent)

    def capture_url(self):
        return reverse("guestbook:capture", kwargs={"pk": self.event.pk})

    def test_non_agent_cannot_access_agent_home(self):
        self.client.login(username="organizer", password="secret")

        response = self.client.get(reverse("guestbook:agent_home"))

        self.assertEqual(response.status_code, 404)

    def test_agent_home_lists_assigned_missions(self):
        self.client.login(username="agent1", password="secret")

        response = self.client.get(reverse("guestbook:agent_home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Mariage Livre d&#x27;Or")

    def test_agent_cannot_access_mission_not_assigned_to_them(self):
        self.client.login(username="agent2", password="secret")

        response = self.client.get(self.capture_url())

        self.assertEqual(response.status_code, 404)

    def test_visiting_capture_screen_starts_the_shift_automatically(self):
        self.client.login(username="agent1", password="secret")
        self.assertIsNone(self.assignment.started_at)

        response = self.client.get(self.capture_url())

        self.assertEqual(response.status_code, 200)
        self.assignment.refresh_from_db()
        self.assertIsNotNone(self.assignment.started_at)

    @patch("guestbook.forms._probe_video_duration", return_value=18)
    def test_agent_records_a_message(self, _probe_video_duration):
        self.client.login(username="agent1", password="secret")
        media = SimpleUploadedFile("message.mp4", b"video", content_type="video/mp4")

        response = self.client.post(
            self.capture_url(),
            {"guest_name": "La famille Dupont", "media_file": media},
        )

        self.assertRedirects(response, self.capture_url())
        message = GuestBookMessage.objects.get(event=self.event)
        self.assertEqual(message.guest_name, "La famille Dupont")
        self.assertEqual(message.recorded_by, self.agent)
        self.assertEqual(message.duration.total_seconds(), 18)

    @patch("guestbook.forms._probe_video_duration", return_value=45)
    def test_rejects_message_over_the_duration_limit(self, _probe_video_duration):
        from django.conf import settings

        self.client.login(username="agent1", password="secret")
        media = SimpleUploadedFile("message.mp4", b"video", content_type="video/mp4")

        response = self.client.post(self.capture_url(), {"media_file": media})

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f"Ce message dépasse {settings.MEMORA_GUESTBOOK_MAX_VIDEO_DURATION_SECONDS} secondes.",
        )
        self.assertEqual(GuestBookMessage.objects.count(), 0)

    def test_ending_shift_closes_the_guestbook(self):
        self.client.login(username="agent1", password="secret")
        self.client.get(self.capture_url())

        response = self.client.post(reverse("guestbook:end_shift", kwargs={"pk": self.event.pk}))

        self.assertRedirects(response, reverse("guestbook:agent_home"))
        self.assignment.refresh_from_db()
        self.assertIsNotNone(self.assignment.ended_at)
        self.assertFalse(self.event.guestbook_is_open)

        closed_response = self.client.get(self.capture_url())
        self.assertContains(closed_response, "Service terminé")

    def test_two_agents_can_work_the_same_event_independently(self):
        second_assignment = GuestBookAssignment.objects.create(
            event=self.event, agent=self.other_agent
        )

        self.client.login(username="agent1", password="secret")
        self.client.get(self.capture_url())
        self.client.post(reverse("guestbook:end_shift", kwargs={"pk": self.event.pk}))

        self.client.login(username="agent2", password="secret")
        response = self.client.get(self.capture_url())

        # Le service de l'agent 1 est termine, mais l'agent 2 peut toujours
        # enregistrer : chaque agent a son propre service, sur son propre compte.
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "guestbook/capture.html")
        self.assertTemplateNotUsed(response, "guestbook/shift_closed.html")
        second_assignment.refresh_from_db()
        self.assertIsNone(second_assignment.ended_at)
        self.assertTrue(self.event.guestbook_is_open)

    def test_agent_home_only_lists_own_assignments(self):
        GuestBookAssignment.objects.create(event=self.event, agent=self.other_agent)

        self.client.login(username="agent2", password="secret")
        response = self.client.get(reverse("guestbook:agent_home"))

        self.assertEqual(len(response.context["assignments"]), 1)
        self.assertEqual(response.context["assignments"][0].agent, self.other_agent)

    def test_capture_screen_shows_recorded_count_and_recent(self):
        GuestBookMessage.objects.create(
            event=self.event,
            guest_name="Les voisins",
            media_file="events/mariage/livre-dor/message.mp4",
            original_filename="message.mp4",
            file_size=1024,
            recorded_by=self.agent,
        )
        self.client.login(username="agent1", password="secret")

        response = self.client.get(self.capture_url())

        self.assertContains(response, "message enregistré")
        self.assertContains(response, "Les voisins")

    def test_agent_home_shows_message_count_per_mission(self):
        GuestBookMessage.objects.create(
            event=self.event,
            media_file="events/mariage/livre-dor/a.mp4",
            original_filename="a.mp4",
            file_size=10,
            recorded_by=self.agent,
        )
        self.client.login(username="agent1", password="secret")

        response = self.client.get(reverse("guestbook:agent_home"))

        self.assertContains(response, "Messages")

    def test_organizer_page_shows_the_montage_not_each_message(self):
        for name in ("Les voisins", "Tata Jeanne"):
            GuestBookMessage.objects.create(
                event=self.event,
                guest_name=name,
                media_file=f"events/mariage/livre-dor/{name}.mp4",
                original_filename="message.mp4",
                file_size=1024,
                recorded_by=self.agent,
            )
        self.client.login(username="organizer", password="secret")

        response = self.client.get(reverse("events:guestbook_messages", kwargs={"pk": self.event.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "2 messages enregistrés")
        # L'organisateur n'a besoin que de la video finale : aucun message isole.
        self.assertNotContains(response, "Les voisins")
        self.assertNotContains(response, "<video")

    def test_guestbook_messages_limited_to_owner(self):
        other_organizer = get_user_model().objects.create_user(username="other-orga", password="secret")
        self.client.login(username="other-orga", password="secret")

        response = self.client.get(reverse("events:guestbook_messages", kwargs={"pk": self.event.pk}))

        self.assertEqual(response.status_code, 404)


class GuestBookMontageTests(TestCase):
    def setUp(self):
        self.agent = get_user_model().objects.create_user(username="agent-m", password="secret")
        AgentProfile.objects.create(user=self.agent)
        self.organizer = get_user_model().objects.create_user(username="orga-m", password="secret")
        self.event = Event.objects.create(
            organizer=self.organizer,
            title="Mariage Montage",
            event_type=EventType.objects.get(code="wedding"),
            event_date=date(2026, 7, 8),
        )
        self.assignment = GuestBookAssignment.objects.create(event=self.event, agent=self.agent)

    def _add_message(self, name="La famille Dupont"):
        return GuestBookMessage.objects.create(
            event=self.event,
            guest_name=name,
            media_file="events/mariage-montage/livre-dor/m.mp4",
            original_filename="m.mp4",
            file_size=2048,
            duration=timedelta(seconds=18),
            recorded_by=self.agent,
        )

    def test_ending_shift_queues_the_montage(self):
        self._add_message()
        self.client.login(username="agent-m", password="secret")
        self.client.get(reverse("guestbook:capture", kwargs={"pk": self.event.pk}))

        self.client.post(reverse("guestbook:end_shift", kwargs={"pk": self.event.pk}))

        movie = GuestBookMovie.objects.get(event=self.event)
        self.assertEqual(movie.status, GuestBookMovie.Status.PENDING)
        self.assertEqual(movie.trigger, "agent_end_shift")

    def test_ending_shift_without_messages_queues_nothing(self):
        self.client.login(username="agent-m", password="secret")
        self.client.get(reverse("guestbook:capture", kwargs={"pk": self.event.pk}))

        self.client.post(reverse("guestbook:end_shift", kwargs={"pk": self.event.pk}))

        self.assertFalse(GuestBookMovie.objects.filter(event=self.event).exists())

    def test_organizer_can_trigger_montage(self):
        self._add_message()
        self.client.login(username="orga-m", password="secret")

        response = self.client.post(
            reverse("events:generate_guestbook_movie", kwargs={"pk": self.event.pk})
        )

        self.assertRedirects(
            response, reverse("events:guestbook_messages", kwargs={"pk": self.event.pk})
        )
        self.assertEqual(
            GuestBookMovie.objects.get(event=self.event).trigger, "organizer_request"
        )

    def test_organizer_trigger_is_owner_only(self):
        self._add_message()
        get_user_model().objects.create_user(username="intruder", password="secret")
        self.client.login(username="intruder", password="secret")

        response = self.client.post(
            reverse("events:generate_guestbook_movie", kwargs={"pk": self.event.pk})
        )

        self.assertEqual(response.status_code, 404)

    def test_abandoned_shift_is_picked_up(self):
        self._add_message()
        old = timezone.now() - timedelta(hours=48)
        GuestBookAssignment.objects.filter(pk=self.assignment.pk).update(
            started_at=old, ended_at=None
        )

        queued = queue_abandoned_guestbook_movies()

        self.assertEqual(queued, 1)
        self.assertEqual(
            GuestBookMovie.objects.get(event=self.event).trigger, "auto_abandon"
        )
        self.assignment.refresh_from_db()
        # Le service abandonne est cloture d'office : il ne redeclenche pas a
        # chaque passage du cron, et l'agent voit son service comme termine.
        self.assertIsNotNone(self.assignment.ended_at)

    def test_abandoned_shift_of_one_agent_does_not_reflag_forever(self):
        self._add_message()
        old = timezone.now() - timedelta(hours=48)
        GuestBookAssignment.objects.filter(pk=self.assignment.pk).update(
            started_at=old, ended_at=None
        )

        first_pass = queue_abandoned_guestbook_movies()
        second_pass = queue_abandoned_guestbook_movies()

        self.assertEqual(first_pass, 1)
        self.assertEqual(second_pass, 0)

    def test_process_guestbook_movie_completes(self):
        self._add_message("Les voisins")
        self._add_message("Tata Jeanne")
        movie = GuestBookMovie.objects.create(event=self.event)

        fake_render = _fake_render()

        with patch(
            "processing.guestbook_montage.render_guestbook_montage", side_effect=fake_render
        ), patch("processing.guestbook_montage.shutil.which", return_value="/usr/bin/ffmpeg"):
            from processing.guestbook_montage import process_guestbook_movie

            process_guestbook_movie(movie)

        movie.refresh_from_db()
        self.assertEqual(movie.status, GuestBookMovie.Status.COMPLETED)
        self.assertTrue(movie.final_file)
        self.assertEqual(movie.message_count, 2)

    def test_process_guestbook_movie_reports_progress_during_render(self):
        """Sans ceci, l'organisateur voit un montage 'en preparation' sans savoir
        s'il avance vraiment ou s'il est bloque (cas remonte en production)."""
        self._add_message("Les voisins")
        movie = GuestBookMovie.objects.create(event=self.event)
        observed = []

        def fake_render(event, messages, output_path, light_output_path=None, progress_callback=None):
            progress_callback(0.5, "Montage des messages (1/1).")
            # Verifie que la progression est bien persistee en base pendant
            # le rendu (pas seulement gardee en memoire) : c'est ce que la
            # page /livre-dor/ interroge en sondant toutes les 5 secondes.
            observed.append(GuestBookMovie.objects.get(pk=movie.pk).progress_percent)
            return _write_montage_files(output_path, light_output_path)

        with patch(
            "processing.guestbook_montage.render_guestbook_montage", side_effect=fake_render
        ), patch("processing.guestbook_montage.shutil.which", return_value="/usr/bin/ffmpeg"):
            from processing.guestbook_montage import process_guestbook_movie

            process_guestbook_movie(movie)

        self.assertEqual(observed, [49.0])
        movie.refresh_from_db()
        self.assertEqual(movie.status, GuestBookMovie.Status.COMPLETED)
        self.assertEqual(movie.progress_percent, 100.0)
