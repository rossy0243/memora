from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase

from events.models import Event, EventType

from .models import GeneratedMovie


class GeneratedMovieModelTests(TestCase):
    def test_generated_movie_defaults_to_pending(self):
        organizer = get_user_model().objects.create_user(
            username="organizer",
            password="secret",
        )
        event_type = EventType.objects.get(code="wedding")
        event = Event.objects.create(
            organizer=organizer,
            title="Mariage Memora",
            event_type=event_type,
            event_date=date(2026, 7, 8),
        )

        movie = GeneratedMovie.objects.create(event=event)

        self.assertEqual(movie.status, GeneratedMovie.Status.PENDING)
        self.assertIsNone(movie.final_file.name or None)
