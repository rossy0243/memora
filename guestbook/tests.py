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

from .models import GuestBookMessage, GuestBookMovie
from .services import queue_abandoned_guestbook_movies


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
            guestbook_agent=self.agent,
        )

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
        self.assertIsNone(self.event.guestbook_started_at)

        response = self.client.get(self.capture_url())

        self.assertEqual(response.status_code, 200)
        self.event.refresh_from_db()
        self.assertIsNotNone(self.event.guestbook_started_at)

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
        self.event.refresh_from_db()
        self.assertIsNotNone(self.event.guestbook_ended_at)
        self.assertFalse(self.event.guestbook_is_open)

        closed_response = self.client.get(self.capture_url())
        self.assertContains(closed_response, "Service terminé")

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

    def test_organizer_can_view_guestbook_messages(self):
        GuestBookMessage.objects.create(
            event=self.event,
            guest_name="Les voisins",
            media_file="events/mariage/livre-dor/message.mp4",
            original_filename="message.mp4",
            file_size=1024,
            recorded_by=self.agent,
        )
        self.client.login(username="organizer", password="secret")

        response = self.client.get(reverse("events:guestbook_messages", kwargs={"pk": self.event.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Les voisins")

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
            guestbook_agent=self.agent,
        )

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
        Event.objects.filter(pk=self.event.pk).update(
            guestbook_started_at=old, guestbook_ended_at=None
        )

        queued = queue_abandoned_guestbook_movies()

        self.assertEqual(queued, 1)
        self.assertEqual(
            GuestBookMovie.objects.get(event=self.event).trigger, "auto_abandon"
        )

    def test_process_guestbook_movie_completes(self):
        self._add_message("Les voisins")
        self._add_message("Tata Jeanne")
        movie = GuestBookMovie.objects.create(event=self.event)

        def fake_render(event, messages, output_path):
            Path(output_path).write_bytes(b"fake-mp4-bytes")
            return Path(output_path)

        with patch(
            "processing.guestbook_montage.render_guestbook_montage", side_effect=fake_render
        ), patch("processing.guestbook_montage.shutil.which", return_value="/usr/bin/ffmpeg"):
            from processing.guestbook_montage import process_guestbook_movie

            process_guestbook_movie(movie)

        movie.refresh_from_db()
        self.assertEqual(movie.status, GuestBookMovie.Status.COMPLETED)
        self.assertTrue(movie.final_file)
        self.assertEqual(movie.message_count, 2)

    def test_build_guestbook_props_interleaves_name_cards(self):
        self._add_message("Les voisins")
        from processing.guestbook_montage import build_guestbook_props

        messages = list(self.event.guestbook_messages.order_by("created_at"))
        props = build_guestbook_props(self.event, messages, None)

        self.assertEqual(len(props["messages"]), 1)
        self.assertEqual(props["messages"][0]["guestName"], "Les voisins")
        self.assertGreater(props["messages"][0]["durationInFrames"], 0)
        self.assertEqual(props["subtitle"], "Livre d'or")


class RoleAwareLoginTests(TestCase):
    def setUp(self):
        self.event_type = EventType.objects.get(code="wedding")

    def test_agent_login_redirects_to_agent_home(self):
        agent = get_user_model().objects.create_user(username="agent-login", password="secret")
        AgentProfile.objects.create(user=agent)

        response = self.client.post(
            reverse("accounts:login"),
            {"username": "agent-login", "password": "secret"},
        )

        self.assertRedirects(response, reverse("guestbook:agent_home"))

    def test_organizer_login_redirects_to_dashboard(self):
        get_user_model().objects.create_user(username="organizer-login", password="secret")

        response = self.client.post(
            reverse("accounts:login"),
            {"username": "organizer-login", "password": "secret"},
        )

        self.assertRedirects(response, reverse("dashboard:home"))

    def test_agent_is_bounced_from_organizer_areas(self):
        agent = get_user_model().objects.create_user(username="agent-isolation", password="secret")
        AgentProfile.objects.create(user=agent)
        self.client.login(username="agent-isolation", password="secret")

        # Le dashboard organisateur et la creation d'evenement renvoient l'agent
        # vers son espace : il ne doit pas voir "la meme chose qu'un organisateur".
        self.assertRedirects(self.client.get(reverse("dashboard:home")), reverse("guestbook:agent_home"))
        self.assertRedirects(self.client.get(reverse("events:create")), reverse("guestbook:agent_home"))
