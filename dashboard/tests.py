from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from events.models import Event, EventType
from processing.models import GeneratedMovie

from .views import _event_post_status


class EventPostStatusTests(TestCase):
    def setUp(self):
        self.organizer = get_user_model().objects.create_user(
            username="organizer",
            email="organizer@example.com",
            password="secret",
        )
        self.event_type, _ = EventType.objects.get_or_create(
            code="wedding",
            defaults={"label": "Mariage", "sort_order": 1},
        )
        self.today = date(2026, 7, 16)

    def _build_event(self, event_date, latest_movie=None):
        event = Event.objects.create(
            organizer=self.organizer,
            title="Mariage Camille",
            event_type=self.event_type,
            event_date=event_date,
        )
        event.latest_movie = latest_movie
        return event

    def test_completed_movie_with_file_is_ready(self):
        movie = GeneratedMovie(status=GeneratedMovie.Status.COMPLETED, final_file="events/x/movies/final.mp4")
        event = self._build_event(self.today - timedelta(days=1), latest_movie=movie)

        self.assertEqual(_event_post_status(event, self.today)["label"], "Film prêt")

    def test_processing_movie(self):
        movie = GeneratedMovie(status=GeneratedMovie.Status.PROCESSING)
        event = self._build_event(self.today - timedelta(days=1), latest_movie=movie)

        self.assertEqual(_event_post_status(event, self.today)["label"], "Film en cours")

    def test_pending_movie(self):
        movie = GeneratedMovie(status=GeneratedMovie.Status.PENDING)
        event = self._build_event(self.today - timedelta(days=1), latest_movie=movie)

        self.assertEqual(_event_post_status(event, self.today)["label"], "Film programmé")

    def test_failed_movie_needs_retry(self):
        movie = GeneratedMovie(status=GeneratedMovie.Status.FAILED)
        event = self._build_event(self.today - timedelta(days=1), latest_movie=movie)

        self.assertEqual(_event_post_status(event, self.today)["label"], "À relancer")

    def test_upcoming_event_without_movie(self):
        event = self._build_event(self.today + timedelta(days=5))

        self.assertEqual(_event_post_status(event, self.today)["label"], "Avant événement")

    def test_event_day_without_movie(self):
        event = self._build_event(self.today)

        self.assertEqual(_event_post_status(event, self.today)["label"], "Jour J")

    def test_past_event_without_movie(self):
        event = self._build_event(self.today - timedelta(days=2))

        self.assertEqual(_event_post_status(event, self.today)["label"], "Film prévu")


class DashboardHomeViewTests(TestCase):
    def setUp(self):
        self.organizer = get_user_model().objects.create_user(
            username="organizer",
            email="organizer@example.com",
            password="secret",
        )
        self.other_organizer = get_user_model().objects.create_user(
            username="other",
            email="other@example.com",
            password="secret",
        )
        self.event_type, _ = EventType.objects.get_or_create(
            code="wedding",
            defaults={"label": "Mariage", "sort_order": 1},
        )

    def test_requires_login(self):
        response = self.client.get(reverse("dashboard:home"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)

    def test_lists_only_own_events(self):
        Event.objects.create(
            organizer=self.organizer,
            title="Mon mariage",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
        )
        Event.objects.create(
            organizer=self.other_organizer,
            title="Mariage d'un autre",
            event_type=self.event_type,
            event_date=date(2026, 7, 9),
        )
        self.client.login(username="organizer", password="secret")

        response = self.client.get(reverse("dashboard:home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Mon mariage")
        self.assertNotContains(response, "Mariage d&#x27;un autre")

    def test_shows_ready_movie_status(self):
        event = Event.objects.create(
            organizer=self.organizer,
            title="Mariage avec film",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
        )
        GeneratedMovie.objects.create(
            event=event,
            status=GeneratedMovie.Status.COMPLETED,
            final_file="events/mariage/movies/final.mp4",
        )
        self.client.login(username="organizer", password="secret")

        response = self.client.get(reverse("dashboard:home"))

        self.assertContains(response, "Film prêt")
