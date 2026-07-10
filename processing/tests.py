from datetime import date, timedelta
from io import BytesIO, StringIO
from pathlib import Path
import shutil
from types import SimpleNamespace
import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from events.models import Event, EventType
from uploads.models import GuestUpload

from .models import GeneratedMovie
from .services import (
    _build_movie_clip,
    create_event_movie_job,
    generate_event_movie,
    get_event_movie_schedule_at,
    get_movie_candidate_uploads,
    process_pending_movie_jobs,
)


TEST_MEDIA_ROOT = tempfile.mkdtemp()


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


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class MovieGenerationServiceTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.organizer = get_user_model().objects.create_user(
            username="organizer",
            password="secret",
        )
        self.event_type = EventType.objects.get(code="wedding")
        self.event = Event.objects.create(
            organizer=self.organizer,
            title="Mariage Film",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
        )
        self.category = self.event.upload_categories.get(code="ceremony")

    def create_upload(
        self,
        filename,
        media_type,
        selected=False,
        rejected=False,
        category_code="ceremony",
        file_size=11,
        duration=None,
    ):
        category = self.event.upload_categories.get(code=category_code)
        return GuestUpload.objects.create(
            event=self.event,
            category=category,
            media_file=SimpleUploadedFile(filename, b"media-bytes", content_type="image/jpeg"),
            media_type=media_type,
            original_filename=filename,
            file_size=file_size,
            duration=duration,
            is_selected_for_movie=selected,
            moderation_status=(
                GuestUpload.ModerationStatus.REJECTED
                if rejected
                else GuestUpload.ModerationStatus.APPROVED
            ),
        )

    @override_settings(MEMORA_MOVIE_MAX_DURATION_SECONDS=20, MEMORA_MOVIE_VIDEO_MAX_SECONDS=10)
    def test_movie_candidates_select_best_videos_automatically(self):
        self.create_upload("selected-photo.jpg", GuestUpload.MediaType.IMAGE, selected=True)
        best_video = self.create_upload(
            "best.mp4",
            GuestUpload.MediaType.VIDEO,
            category_code="emotional",
            file_size=40_000_000,
            duration=timedelta(seconds=8),
        )
        second_video = self.create_upload(
            "second.mp4",
            GuestUpload.MediaType.VIDEO,
            category_code="dancefloor",
            file_size=20_000_000,
            duration=timedelta(seconds=9),
        )
        self.create_upload("rejected.mp4", GuestUpload.MediaType.VIDEO, rejected=True)

        candidates = list(get_movie_candidate_uploads(self.event))

        self.assertEqual(candidates, [best_video, second_video])

    @override_settings(MEMORA_MOVIE_MAX_DURATION_SECONDS=20, MEMORA_MOVIE_VIDEO_MAX_SECONDS=10)
    def test_movie_candidates_never_exceed_movie_duration_cap(self):
        for index in range(4):
            self.create_upload(
                f"video-{index}.mp4",
                GuestUpload.MediaType.VIDEO,
                file_size=10_000_000 + index,
                duration=timedelta(seconds=10),
            )

        candidates = list(get_movie_candidate_uploads(self.event))

        self.assertEqual(len(candidates), 2)

    def test_generate_event_movie_fails_without_media(self):
        movie = generate_event_movie(self.event)

        self.assertEqual(movie.status, GeneratedMovie.Status.FAILED)
        self.assertIn("Aucun media", movie.error_logs)

    def test_create_event_movie_job_reuses_pending_job(self):
        first_job = create_event_movie_job(self.event)
        second_job = create_event_movie_job(self.event)

        self.assertEqual(first_job, second_job)
        self.assertEqual(GeneratedMovie.objects.filter(event=self.event).count(), 1)

    def test_process_pending_movie_jobs_processes_pending_jobs(self):
        movie = create_event_movie_job(self.event)

        with patch("processing.services.process_generated_movie") as process_generated_movie:
            process_generated_movie.return_value = movie

            processed_movies = process_pending_movie_jobs()

        process_generated_movie.assert_called_once_with(movie)
        self.assertEqual(processed_movies, [movie])

    @patch("processing.services.shutil.which", return_value="ffmpeg")
    @patch("processing.services._run_ffmpeg")
    def test_generate_event_movie_creates_completed_movie(self, run_ffmpeg, _which):
        self.create_upload("photo.jpg", GuestUpload.MediaType.IMAGE, selected=True)

        def create_output(command):
            Path(command[-1]).write_bytes(b"movie-bytes")

        run_ffmpeg.side_effect = create_output

        movie = generate_event_movie(self.event)

        self.assertEqual(movie.status, GeneratedMovie.Status.COMPLETED)
        self.assertTrue(movie.final_file.name.endswith(".mp4"))
        self.assertIsNotNone(movie.generated_at)
        self.assertLessEqual(movie.duration.total_seconds(), 300)
        self.assertGreaterEqual(run_ffmpeg.call_count, 2)

    @patch("processing.services._run_ffmpeg")
    def test_movie_clip_can_use_storage_without_local_path(self, run_ffmpeg):
        class RemoteOnlyMedia:
            name = "remote/video.mp4"

            def __init__(self):
                self.file = BytesIO(b"remote-media")

            def open(self, mode="rb"):
                self.file.seek(0)

            def chunks(self):
                yield self.file.read()

            def close(self):
                pass

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "clip.mp4"
            upload = SimpleNamespace(
                pk=123,
                media_file=RemoteOnlyMedia(),
                media_type=GuestUpload.MediaType.VIDEO,
                original_filename="video.mp4",
            )

            def create_output(command):
                input_path = Path(command[command.index("-i") + 1])
                self.assertTrue(input_path.exists())
                output_path.write_bytes(b"movie-bytes")

            run_ffmpeg.side_effect = create_output

            _build_movie_clip(upload, output_path, "ffmpeg")

        run_ffmpeg.assert_called_once()


class GenerateScheduledMoviesCommandTests(TestCase):
    def setUp(self):
        self.organizer = get_user_model().objects.create_user(
            username="organizer",
            password="secret",
        )
        self.event_type = EventType.objects.get(code="wedding")

    def create_event_with_video(self, event_date, title="Mariage planifie"):
        event = Event.objects.create(
            organizer=self.organizer,
            title=title,
            event_type=self.event_type,
            event_date=event_date,
        )
        GuestUpload.objects.create(
            event=event,
            category=event.upload_categories.get(code="dancefloor"),
            media_file="events/test/uploads/dancefloor/video.mp4",
            media_type=GuestUpload.MediaType.VIDEO,
            original_filename="video.mp4",
            file_size=10_000_000,
            duration=timedelta(seconds=8),
        )
        return event

    @override_settings(MEMORA_MOVIE_AUTOGENERATE_HOUR=12)
    def test_movie_schedule_is_day_after_event_at_noon(self):
        event = self.create_event_with_video(date(2026, 7, 8))

        scheduled_at = timezone.localtime(get_event_movie_schedule_at(event))

        self.assertEqual(scheduled_at.date(), date(2026, 7, 9))
        self.assertEqual(scheduled_at.hour, 12)
        self.assertEqual(scheduled_at.minute, 0)

    @override_settings(MEMORA_MOVIE_AUTOGENERATE_HOUR=0)
    @patch("processing.management.commands.generate_scheduled_movies.create_event_movie_job")
    def test_generates_due_movies(self, create_movie_job):
        event = self.create_event_with_video(timezone.localdate() - timedelta(days=1))
        create_movie_job.return_value = GeneratedMovie(
            event=event,
            status=GeneratedMovie.Status.PENDING,
        )
        output = StringIO()

        call_command("generate_scheduled_movies", stdout=output)

        create_movie_job.assert_called_once_with(event)
        self.assertIn("Mariage planifie", output.getvalue())

    @override_settings(MEMORA_MOVIE_AUTOGENERATE_HOUR=0)
    @patch("processing.management.commands.generate_scheduled_movies.create_event_movie_job")
    def test_dry_run_does_not_generate_movie(self, create_movie_job):
        self.create_event_with_video(timezone.localdate() - timedelta(days=1))
        output = StringIO()

        call_command("generate_scheduled_movies", "--dry-run", stdout=output)

        create_movie_job.assert_not_called()
        self.assertIn("[dry-run]", output.getvalue())

    @override_settings(MEMORA_MOVIE_AUTOGENERATE_HOUR=0)
    @patch("processing.management.commands.generate_scheduled_movies.create_event_movie_job")
    def test_completed_movie_is_not_generated_again(self, create_movie_job):
        event = self.create_event_with_video(timezone.localdate() - timedelta(days=1))
        GeneratedMovie.objects.create(event=event, status=GeneratedMovie.Status.COMPLETED)

        call_command("generate_scheduled_movies")

        create_movie_job.assert_not_called()

    @override_settings(MEMORA_MOVIE_AUTOGENERATE_HOUR=0)
    @patch("processing.management.commands.generate_scheduled_movies.process_generated_movie")
    def test_process_now_processes_created_job(self, process_generated_movie):
        event = self.create_event_with_video(timezone.localdate() - timedelta(days=1))

        call_command("generate_scheduled_movies", "--process-now")

        movie = GeneratedMovie.objects.get(event=event)
        process_generated_movie.assert_called_once_with(movie)


class ProcessPendingMoviesCommandTests(TestCase):
    def setUp(self):
        organizer = get_user_model().objects.create_user(
            username="organizer",
            password="secret",
        )
        event_type = EventType.objects.get(code="wedding")
        self.event = Event.objects.create(
            organizer=organizer,
            title="Film Worker",
            event_type=event_type,
            event_date=date(2026, 7, 8),
        )

    @patch("processing.management.commands.process_pending_movies.process_generated_movie")
    def test_processes_pending_movies(self, process_generated_movie):
        movie = GeneratedMovie.objects.create(event=self.event, status=GeneratedMovie.Status.PENDING)
        process_generated_movie.return_value = movie

        call_command("process_pending_movies")

        process_generated_movie.assert_called_once_with(movie)

    @patch("processing.management.commands.process_pending_movies.process_generated_movie")
    def test_dry_run_does_not_process_movies(self, process_generated_movie):
        GeneratedMovie.objects.create(event=self.event, status=GeneratedMovie.Status.PENDING)
        output = StringIO()

        call_command("process_pending_movies", "--dry-run", stdout=output)

        process_generated_movie.assert_not_called()
        self.assertIn("[dry-run]", output.getvalue())


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
