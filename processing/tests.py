from datetime import date, timedelta
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from events.models import Event, EventType
from uploads.models import GuestUpload

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


class CleanupExpiredMediaCommandTests(TestCase):
    def setUp(self):
        self.organizer = get_user_model().objects.create_user(
            username="organizer",
            password="secret",
        )
        self.event_type = EventType.objects.get(code="wedding")

    def create_upload_for_event_date(self, event_date):
        event = Event.objects.create(
            organizer=self.organizer,
            title=f"Evenement {event_date}",
            event_type=self.event_type,
            event_date=event_date,
        )
        category = event.upload_categories.get(code="ceremony")
        return GuestUpload.objects.create(
            event=event,
            category=category,
            media_file="events/test/uploads/ceremony/photo.jpg",
            media_type=GuestUpload.MediaType.IMAGE,
            original_filename="photo.jpg",
            file_size=10,
        )

    def test_marks_media_deleted_one_week_after_event_day(self):
        today = timezone.localdate()
        expired_upload = self.create_upload_for_event_date(today - timedelta(days=7))
        active_upload = self.create_upload_for_event_date(today - timedelta(days=6))

        call_command("cleanup_expired_media")

        expired_upload.refresh_from_db()
        active_upload.refresh_from_db()
        self.assertTrue(expired_upload.is_deleted)
        self.assertFalse(active_upload.is_deleted)

    def test_dry_run_does_not_mark_media_deleted(self):
        today = timezone.localdate()
        upload = self.create_upload_for_event_date(today - timedelta(days=8))
        output = StringIO()

        call_command("cleanup_expired_media", "--dry-run", stdout=output)

        upload.refresh_from_db()
        self.assertFalse(upload.is_deleted)
        self.assertIn("1 media", output.getvalue())
