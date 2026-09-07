from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from accounts.models import AgentProfile
from events.models import Event, EventType

from .models import GuestBookMessage


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
    def test_rejects_message_longer_than_thirty_seconds(self, _probe_video_duration):
        self.client.login(username="agent1", password="secret")
        media = SimpleUploadedFile("message.mp4", b"video", content_type="video/mp4")

        response = self.client.post(self.capture_url(), {"media_file": media})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ce message dépasse 30 secondes.")
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
