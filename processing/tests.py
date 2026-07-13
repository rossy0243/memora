from datetime import date, timedelta
from io import BytesIO, StringIO
from pathlib import Path
import shutil
from types import SimpleNamespace
import tempfile
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image

from events.models import Event, EventType
from uploads.models import GuestUpload

from .analysis import _score_upload, analyze_pending_media, create_media_analysis_job, create_missing_media_analysis_jobs
from .models import GeneratedMovie, MediaAnalysis
from .services import (
    _apply_event_badge,
    _build_movie_clip,
    _shorten_badge_text,
    create_event_movie_job,
    generate_event_movie,
    get_event_movie_schedule_at,
    get_movie_candidate_uploads,
    process_pending_movie_jobs,
)
from .soundtrack import build_edit_decision_data, choose_movie_soundtrack


TEST_MEDIA_ROOT = tempfile.mkdtemp()


def make_test_image_bytes(color=(180, 160, 140)):
    buffer = BytesIO()
    image = Image.new("RGB", (120, 80), color=color)
    image.save(buffer, format="JPEG")
    return buffer.getvalue()


def _candidate_duration(upload):
    if upload.media_type == GuestUpload.MediaType.IMAGE:
        return settings.MEMORA_MOVIE_IMAGE_DURATION_SECONDS
    return int(upload.duration.total_seconds()) if upload.duration else settings.MEMORA_MOVIE_VIDEO_MAX_SECONDS


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
        self.assertEqual(movie.render_provider, "ffmpeg")
        self.assertIsNone(movie.final_file.name or None)


class MediaAnalysisModelTests(TestCase):
    def test_media_analysis_defaults_to_pending(self):
        organizer = get_user_model().objects.create_user(
            username="organizer",
            password="secret",
        )
        event_type = EventType.objects.get(code="wedding")
        event = Event.objects.create(
            organizer=organizer,
            title="Mariage Analyse",
            event_type=event_type,
            event_date=date(2026, 7, 8),
        )
        upload = GuestUpload.objects.create(
            event=event,
            category=event.upload_categories.get(code="ceremony"),
            media_file=SimpleUploadedFile("photo.jpg", make_test_image_bytes(), content_type="image/jpeg"),
            media_type=GuestUpload.MediaType.IMAGE,
            original_filename="photo.jpg",
            file_size=100,
        )

        analysis = MediaAnalysis.objects.create(upload=upload)

        self.assertEqual(analysis.status, MediaAnalysis.Status.PENDING)
        self.assertEqual(analysis.provider, "local_heuristic_v1")
        self.assertEqual(analysis.provider_payload, {})


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class MediaAnalysisServiceTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.organizer = get_user_model().objects.create_user(
            username="organizer-analysis",
            password="secret",
        )
        self.event_type = EventType.objects.get(code="wedding")
        self.event = Event.objects.create(
            organizer=self.organizer,
            title="Mariage Analyse Service",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
        )
        self.category = self.event.upload_categories.get(code="emotional")

    def create_image_upload(self, filename="photo.jpg"):
        image_bytes = make_test_image_bytes()
        return GuestUpload.objects.create(
            event=self.event,
            category=self.category,
            media_file=SimpleUploadedFile(filename, image_bytes, content_type="image/jpeg"),
            media_type=GuestUpload.MediaType.IMAGE,
            original_filename=filename,
            file_size=len(image_bytes),
        )

    def test_create_missing_media_analysis_jobs(self):
        upload = self.create_image_upload()

        analyses = create_missing_media_analysis_jobs()

        self.assertEqual(analyses, [upload.analysis])
        self.assertEqual(upload.analysis.status, MediaAnalysis.Status.PENDING)

    def test_analyze_pending_media_scores_image(self):
        upload = self.create_image_upload()
        create_media_analysis_job(upload)

        analyses = analyze_pending_media()

        analysis = analyses[0]
        self.assertEqual(analysis.status, MediaAnalysis.Status.COMPLETED)
        self.assertGreater(analysis.movie_score, 0)
        self.assertIn("image", analysis.tags)
        self.assertTrue(analysis.summary)

    def test_analyze_pending_media_dry_run_command_does_not_create_jobs(self):
        upload = self.create_image_upload()
        output = StringIO()

        call_command("analyze_pending_media", "--dry-run", stdout=output)

        self.assertFalse(MediaAnalysis.objects.filter(upload=upload).exists())
        self.assertIn("[dry-run]", output.getvalue())

    @patch("processing.management.commands.analyze_pending_media.sleep", side_effect=KeyboardInterrupt)
    def test_analyze_pending_media_loop_waits_between_passes(self, sleep_mock):
        output = StringIO()

        with self.assertRaises(KeyboardInterrupt):
            call_command("analyze_pending_media", "--loop", "--sleep", "1", stdout=output)

        sleep_mock.assert_called_once_with(1)

    def test_google_provider_payload_boosts_human_voice_moments(self):
        upload = self.create_image_upload()
        metrics = {"brightness": 55, "contrast": 60, "sharpness": 60}
        payload = {
            "provider": "google_video_intelligence_v1",
            "labels": [{"description": "wedding", "confidence": 0.91}],
            "face_track_count": 3,
            "shot_count": 4,
            "speech_segments": [{"transcript": "merci a tous", "confidence": 0.85}],
            "explicit_content": {"max_likelihood": 1, "max_likelihood_name": "VERY_UNLIKELY"},
        }

        scores = _score_upload(upload, metrics, provider_payload=payload)

        self.assertIn("visages", scores["tags"])
        self.assertIn("voix", scores["tags"])
        self.assertIn("moment_humain", scores["tags"])
        self.assertGreater(scores["movie_score"], 70)

    def test_google_provider_payload_penalizes_sensitive_content(self):
        upload = self.create_image_upload()
        metrics = {"brightness": 55, "contrast": 60, "sharpness": 60}
        payload = {
            "provider": "google_video_intelligence_v1",
            "labels": [],
            "face_track_count": 0,
            "shot_count": 1,
            "speech_segments": [],
            "explicit_content": {"max_likelihood": 5, "max_likelihood_name": "VERY_LIKELY"},
        }

        scores = _score_upload(upload, metrics, provider_payload=payload)

        self.assertIn("contenu_sensible", scores["tags"])
        self.assertLess(scores["movie_score"], 55)


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
    def test_movie_candidates_mix_best_videos_and_photos_automatically(self):
        selected_photo = self.create_upload("selected-photo.jpg", GuestUpload.MediaType.IMAGE, selected=True)
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

        self.assertEqual(candidates, [best_video, second_video, selected_photo])

    @override_settings(
        MEMORA_MOVIE_MAX_DURATION_SECONDS=40,
        MEMORA_MOVIE_VIDEO_MAX_SECONDS=10,
        MEMORA_MOVIE_IMAGE_DURATION_SECONDS=3,
        MEMORA_MOVIE_PHOTO_TARGET_RATIO=0.20,
        MEMORA_MOVIE_MIN_PHOTO_COUNT_WITH_VIDEOS=2,
    )
    def test_movie_candidates_reserve_room_for_photos_when_videos_exist(self):
        for index in range(5):
            self.create_upload(
                f"video-{index}.mp4",
                GuestUpload.MediaType.VIDEO,
                file_size=20_000_000 + index,
                duration=timedelta(seconds=10),
            )
        photo_one = self.create_upload("photo-one.jpg", GuestUpload.MediaType.IMAGE, category_code="emotional")
        photo_two = self.create_upload("photo-two.jpg", GuestUpload.MediaType.IMAGE, category_code="cake")

        candidates = list(get_movie_candidate_uploads(self.event))

        self.assertIn(photo_one, candidates)
        self.assertIn(photo_two, candidates)
        self.assertLessEqual(sum(_candidate_duration(upload) for upload in candidates), 40)
        self.assertGreaterEqual(
            sum(1 for upload in candidates if upload.media_type == GuestUpload.MediaType.VIDEO),
            3,
        )

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

    def test_movie_candidates_use_completed_media_analysis_score(self):
        lower_score = self.create_upload(
            "large.mp4",
            GuestUpload.MediaType.VIDEO,
            file_size=80_000_000,
            duration=timedelta(seconds=8),
        )
        higher_score = self.create_upload(
            "small.mp4",
            GuestUpload.MediaType.VIDEO,
            file_size=1_000_000,
            duration=timedelta(seconds=8),
        )
        MediaAnalysis.objects.create(
            upload=lower_score,
            status=MediaAnalysis.Status.COMPLETED,
            movie_score=40,
        )
        MediaAnalysis.objects.create(
            upload=higher_score,
            status=MediaAnalysis.Status.COMPLETED,
            movie_score=88,
        )

        candidates = list(get_movie_candidate_uploads(self.event))

        self.assertEqual(candidates[0], higher_score)

    @override_settings(MEMORA_MOVIE_MAX_DURATION_SECONDS=600)
    def test_default_movie_duration_cap_is_ten_minutes(self):
        for index in range(61):
            self.create_upload(
                f"video-{index}.mp4",
                GuestUpload.MediaType.VIDEO,
                file_size=10_000_000 + index,
                duration=timedelta(seconds=10),
            )

        candidates = list(get_movie_candidate_uploads(self.event))

        self.assertLessEqual(sum(int(upload.duration.total_seconds()) for upload in candidates), 600)

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
        self.event.couple_name = "Lea & Sam"
        self.event.save(update_fields=["couple_name"])
        self.create_upload("photo.jpg", GuestUpload.MediaType.IMAGE, selected=True)

        def create_output(command):
            Path(command[-1]).write_bytes(b"movie-bytes")

        run_ffmpeg.side_effect = create_output

        movie = generate_event_movie(self.event)

        self.assertEqual(movie.status, GeneratedMovie.Status.COMPLETED)
        self.assertTrue(movie.final_file.name.endswith(".mp4"))
        self.assertIsNotNone(movie.generated_at)
        self.assertLessEqual(movie.duration.total_seconds(), 600)
        self.assertEqual(movie.render_provider, "ffmpeg")
        self.assertTrue(movie.music_mood)
        self.assertIn("clips", movie.edit_decision_data)
        self.assertEqual(movie.edit_decision_data["badge"]["display_name"], "Lea & Sam")
        self.assertTrue(movie.edit_decision_data["badge"]["applied"])
        badge_command = run_ffmpeg.call_args_list[-1].args[0]
        self.assertIn("drawtext", badge_command[badge_command.index("-vf") + 1])
        self.assertGreaterEqual(run_ffmpeg.call_count, 3)

    @patch("processing.services._run_ffmpeg")
    def test_event_badge_uses_display_name_and_preserves_audio_mapping(self, run_ffmpeg):
        self.event.couple_name = "Camille & Noe"
        input_path = Path(TEST_MEDIA_ROOT) / "input.mp4"
        output_path = Path(TEST_MEDIA_ROOT) / "badged.mp4"
        input_path.write_bytes(b"movie")

        def create_output(command):
            Path(command[-1]).write_bytes(b"badged")

        run_ffmpeg.side_effect = create_output

        result = _apply_event_badge(input_path, output_path, self.event, "ffmpeg", Path(TEST_MEDIA_ROOT))

        self.assertEqual(result, output_path)
        command = run_ffmpeg.call_args.args[0]
        self.assertIn("-map", command)
        self.assertIn("0:a?", command)
        self.assertIn("drawbox", command[command.index("-vf") + 1])
        self.assertIn("drawtext", command[command.index("-vf") + 1])
        self.assertIn("font='Arial'", command[command.index("-vf") + 1])
        self.assertIn("y=ih-126", command[command.index("-vf") + 1])

    def test_badge_text_is_shortened_for_clean_video_overlay(self):
        text = _shorten_badge_text("Un tres tres long nom affiche pour un evenement Memora")

        self.assertLessEqual(len(text), 38)
        self.assertTrue(text.endswith("..."))

    @override_settings(
        MEMORA_RUNWAY_ENABLED=True,
        MEMORA_RUNWAY_API_SECRET="test-key",
        MEMORA_MOVIE_RENDER_PROVIDER="runway",
        MEMORA_RUNWAY_MAX_ENHANCED_CLIPS=1,
        MEMORA_RUNWAY_FALLBACK_TO_FFMPEG=True,
    )
    @patch("processing.services.shutil.which", return_value="ffmpeg")
    @patch("processing.services.enhance_clip_with_runway")
    @patch("processing.services._run_ffmpeg")
    def test_runway_enhances_selected_video_before_final_assembly(self, run_ffmpeg, enhance_clip, _which):
        self.create_upload(
            "best.mp4",
            GuestUpload.MediaType.VIDEO,
            category_code="emotional",
            duration=timedelta(seconds=8),
        )

        def create_output(command):
            Path(command[-1]).write_bytes(b"movie-bytes")

        def create_runway_output(_input_path, output_path, prompt_text=None):
            output_path.write_bytes(b"runway-movie-bytes")
            return {"task_id": "task_123", "output_count": 1, "output_file": output_path.name}

        run_ffmpeg.side_effect = create_output
        enhance_clip.side_effect = create_runway_output

        movie = generate_event_movie(self.event)

        self.assertEqual(movie.status, GeneratedMovie.Status.COMPLETED)
        self.assertEqual(movie.render_provider, "runway+ffmpeg")
        self.assertEqual(movie.edit_decision_data["runway"]["enhancements"][0]["task_id"], "task_123")
        enhance_clip.assert_called_once()

    def test_soundtrack_choice_and_edit_plan_are_generated(self):
        upload = self.create_upload(
            "dance.mp4",
            GuestUpload.MediaType.VIDEO,
            category_code="dancefloor",
            duration=timedelta(seconds=8),
        )

        soundtrack = choose_movie_soundtrack(self.event, [upload])
        edit_plan = build_edit_decision_data(self.event, [upload], soundtrack)

        self.assertEqual(soundtrack.mood, "joyful_party")
        self.assertTrue(edit_plan["audio_strategy"]["duck_music_when_voice_is_present"])
        self.assertEqual(edit_plan["max_duration_seconds"], 600)

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

    @patch("processing.services._run_ffmpeg")
    def test_movie_image_clip_gets_silent_audio_for_concat(self, run_ffmpeg):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "clip.mp4"
            upload = SimpleNamespace(
                pk=124,
                media_file=SimpleUploadedFile("photo.jpg", make_test_image_bytes(), content_type="image/jpeg"),
                media_type=GuestUpload.MediaType.IMAGE,
                original_filename="photo.jpg",
            )

            def create_output(command):
                output_path.write_bytes(b"movie-bytes")

            run_ffmpeg.side_effect = create_output

            _build_movie_clip(upload, output_path, "ffmpeg")

        command = run_ffmpeg.call_args.args[0]
        self.assertIn("anullsrc=channel_layout=stereo:sample_rate=48000", command)
        self.assertIn("1:a:0", command)
        self.assertIn("-shortest", command)


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

    @patch("processing.management.commands.process_pending_movies.sleep", side_effect=KeyboardInterrupt)
    def test_loop_mode_waits_between_passes(self, sleep_mock):
        output = StringIO()

        with self.assertRaises(KeyboardInterrupt):
            call_command("process_pending_movies", "--loop", "--sleep", "1", stdout=output)

        sleep_mock.assert_called_once_with(1)


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
