from datetime import date, timedelta
from io import BytesIO, StringIO
from pathlib import Path
import shutil
from types import SimpleNamespace
import tempfile
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from events.models import Event, EventType
from uploads.models import GuestUpload

from . import services
from . import soundtrack as soundtrack_module
from . import title_cards
from .analysis import _score_upload, analyze_pending_media, create_media_analysis_job, create_missing_media_analysis_jobs
from .models import GeneratedMovie, MediaAnalysis
from .services import (
    MOOD_COLOR_GRADE_FILTERS,
    _apply_color_grade,
    _apply_event_badge,
    _build_movie_clip,
    _shorten_badge_text,
    create_event_movie_job,
    generate_event_movie,
    get_event_movie_schedule_at,
    get_pending_movie_jobs,
    get_movie_candidate_uploads,
    notify_generated_movie_ready,
    process_generated_movie,
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
        Path(TEST_MEDIA_ROOT).mkdir(parents=True, exist_ok=True)
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
        self.event.mark_paid(provider="test")
        self.event.save(update_fields=["payment_status", "paid_at", "payment_provider"])
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

    @override_settings(
        MEMORA_MOVIE_MAX_DURATION_SECONDS=20,
        MEMORA_MOVIE_HERO_DURATION_SECONDS=20,
        MEMORA_MOVIE_VIDEO_MAX_SECONDS=10,
    )
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

        # L'ordre final releve de l'arc narratif (teste a part) : ici on verifie la selection.
        self.assertCountEqual(candidates, [best_video, second_video, selected_photo])

    @override_settings(
        MEMORA_MOVIE_MAX_DURATION_SECONDS=40,
        MEMORA_MOVIE_HERO_DURATION_SECONDS=40,
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

    @override_settings(
        MEMORA_MOVIE_MAX_DURATION_SECONDS=20,
        MEMORA_MOVIE_HERO_DURATION_SECONDS=20,
        MEMORA_MOVIE_VIDEO_MAX_SECONDS=10,
    )
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
        self.assertEqual(movie.progress_message, "Aucun souvenir valide disponible pour le film.")
        self.event.refresh_from_db()
        self.assertTrue(self.event.is_active)
        self.assertTrue(self.event.can_accept_guest_uploads)

    def test_create_event_movie_job_requires_paid_event(self):
        self.event.payment_status = Event.PaymentStatus.PENDING
        self.event.paid_at = None
        self.event.save(update_fields=["payment_status", "paid_at"])

        with self.assertRaisesMessage(ValueError, "activation"):
            create_event_movie_job(self.event)

    @patch("processing.services.analyze_event_media", side_effect=RuntimeError("analyse indisponible"))
    def test_generate_event_movie_marks_failed_when_analysis_crashes(self, _analyze_event_media):
        movie = create_event_movie_job(self.event)

        processed = process_generated_movie(movie)

        self.assertEqual(processed.status, GeneratedMovie.Status.FAILED)
        self.assertIn("analyse indisponible", processed.error_logs)

    def test_create_event_movie_job_reuses_pending_job(self):
        first_job = create_event_movie_job(self.event)
        second_job = create_event_movie_job(self.event)

        self.assertEqual(first_job, second_job)
        self.assertEqual(first_job.progress_percent, 5)
        self.assertIn("planifié", first_job.progress_message)
        self.assertEqual(GeneratedMovie.objects.filter(event=self.event).count(), 1)

    def test_create_event_movie_job_reuses_completed_movie(self):
        completed_movie = GeneratedMovie.objects.create(
            event=self.event,
            status=GeneratedMovie.Status.COMPLETED,
            final_file="events/film/movies/memora.mp4",
        )

        movie = create_event_movie_job(self.event)

        self.assertEqual(movie, completed_movie)
        self.assertEqual(GeneratedMovie.objects.filter(event=self.event).count(), 1)

    def test_create_event_movie_job_does_not_retry_failed_movie_by_default(self):
        failed_movie = GeneratedMovie.objects.create(
            event=self.event,
            status=GeneratedMovie.Status.FAILED,
            error_logs="provider error",
        )

        movie = create_event_movie_job(self.event)

        self.assertEqual(movie, failed_movie)
        self.assertEqual(GeneratedMovie.objects.filter(event=self.event).count(), 1)

    def test_create_event_movie_job_can_retry_failed_movie_when_requested(self):
        GeneratedMovie.objects.create(
            event=self.event,
            status=GeneratedMovie.Status.FAILED,
            error_logs="provider error",
        )

        movie = create_event_movie_job(self.event, allow_retry=True)

        self.assertEqual(movie.status, GeneratedMovie.Status.PENDING)
        self.assertEqual(GeneratedMovie.objects.filter(event=self.event).count(), 2)

    @override_settings(MEMORA_MOVIE_PROCESSING_STALE_MINUTES=5)
    def test_pending_movie_jobs_include_stale_processing_jobs(self):
        stale_movie = GeneratedMovie.objects.create(
            event=self.event,
            status=GeneratedMovie.Status.PROCESSING,
        )
        recent_movie = GeneratedMovie.objects.create(
            event=self.event,
            status=GeneratedMovie.Status.PROCESSING,
        )
        GeneratedMovie.objects.filter(pk=stale_movie.pk).update(
            updated_at=timezone.now() - timedelta(minutes=10)
        )
        stale_movie.refresh_from_db()

        jobs = get_pending_movie_jobs()

        self.assertIn(stale_movie, jobs)
        self.assertNotIn(recent_movie, jobs)

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
        self.assertEqual(movie.progress_percent, 100)
        self.assertEqual(movie.progress_message, "Votre film souvenir est prêt.")
        self.assertTrue(movie.music_mood)
        self.assertIn("clips", movie.edit_decision_data)
        self.assertEqual(movie.edit_decision_data["badge"]["display_name"], "Lea & Sam")
        self.assertEqual(movie.edit_decision_data["badge"]["display_mode"], "full_movie")
        self.assertIsNone(movie.edit_decision_data["badge"]["duration_seconds"])
        self.assertTrue(movie.edit_decision_data["badge"]["applied"])
        # Le badge n'est plus le dernier appel ffmpeg : les declinaisons sont rendues apres.
        badge_filter = next(
            call.args[0][call.args[0].index("-vf") + 1]
            for call in reversed(run_ffmpeg.call_args_list)
            if "-vf" in call.args[0] and "drawtext" in call.args[0][call.args[0].index("-vf") + 1]
        )
        self.assertIn("drawtext", badge_filter)
        self.assertNotIn("enable=", badge_filter)
        self.assertGreaterEqual(run_ffmpeg.call_count, 3)
        self.event.refresh_from_db()
        self.assertFalse(self.event.is_active)
        self.assertFalse(self.event.can_accept_guest_uploads)

    @override_settings(
        MEMORA_PUBLIC_BASE_URL="https://memora.example",
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    )
    def test_notify_generated_movie_ready_emails_organizer_once(self):
        mail.outbox = []
        self.organizer.email = "organizer@example.com"
        self.organizer.save(update_fields=["email"])
        movie = GeneratedMovie.objects.create(
            event=self.event,
            status=GeneratedMovie.Status.COMPLETED,
            final_file="events/film/movies/memora.mp4",
            generated_at=timezone.now(),
        )

        first_result = notify_generated_movie_ready(movie)
        second_result = notify_generated_movie_ready(movie)

        movie.refresh_from_db()
        self.assertTrue(first_result)
        self.assertFalse(second_result)
        self.assertIsNotNone(movie.organizer_notified_at)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Votre film souvenir Memora est prêt", mail.outbox[0].subject)
        self.assertIn("https://memora.example", mail.outbox[0].body)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_notify_generated_movie_ready_skips_missing_email(self):
        mail.outbox = []
        movie = GeneratedMovie.objects.create(
            event=self.event,
            status=GeneratedMovie.Status.COMPLETED,
            final_file="events/film/movies/memora.mp4",
            generated_at=timezone.now(),
        )

        result = notify_generated_movie_ready(movie)

        self.assertFalse(result)
        self.assertEqual(len(mail.outbox), 0)

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
        self.assertNotIn("enable=", command[command.index("-vf") + 1])

    @patch("processing.services._run_ffmpeg")
    def test_color_grade_applies_mood_filter(self, run_ffmpeg):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "graded_input.mp4"
            output_path = Path(temp_dir) / "graded_output.mp4"
            input_path.write_bytes(b"movie")

            def create_output(command):
                Path(command[-1]).write_bytes(b"graded")

            run_ffmpeg.side_effect = create_output

            result = _apply_color_grade(input_path, output_path, "joyful_party", "ffmpeg")

        self.assertEqual(result, output_path)
        command = run_ffmpeg.call_args.args[0]
        video_filter = command[command.index("-vf") + 1]
        self.assertEqual(video_filter, MOOD_COLOR_GRADE_FILTERS["joyful_party"])

    @patch("processing.services._run_ffmpeg")
    def test_color_grade_falls_back_to_elegant_warm_for_unknown_mood(self, run_ffmpeg):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "graded_input_unknown.mp4"
            output_path = Path(temp_dir) / "graded_output_unknown.mp4"
            input_path.write_bytes(b"movie")

            def create_output(command):
                Path(command[-1]).write_bytes(b"graded")

            run_ffmpeg.side_effect = create_output

            _apply_color_grade(input_path, output_path, "unknown_mood", "ffmpeg")

        command = run_ffmpeg.call_args.args[0]
        video_filter = command[command.index("-vf") + 1]
        self.assertEqual(video_filter, MOOD_COLOR_GRADE_FILTERS["elegant_warm"])

    @patch("processing.services._run_ffmpeg")
    @override_settings(MEMORA_MOVIE_COLOR_GRADE_ENABLED=False)
    def test_color_grade_passthrough_when_disabled(self, run_ffmpeg):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "graded_input_disabled.mp4"

            result = _apply_color_grade(input_path, Path(temp_dir) / "unused.mp4", "joyful_party", "ffmpeg")

        self.assertEqual(result, input_path)
        run_ffmpeg.assert_not_called()

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

    @override_settings(
        MEMORA_RUNWAY_ENABLED=True,
        MEMORA_RUNWAY_API_SECRET="test-key",
        MEMORA_MOVIE_RENDER_PROVIDER="runway_final",
        MEMORA_RUNWAY_WORKFLOW_ID="workflow_123",
        MEMORA_RUNWAY_FALLBACK_TO_FFMPEG=True,
        # Ce test isole le chemin Runway du film heros : pas de declinaisons.
        MEMORA_MOVIE_VARIANTS_ENABLED=False,
    )
    @patch("processing.services.shutil.which", return_value="ffmpeg")
    @patch("processing.services.render_final_movie_with_runway")
    @patch("processing.services._run_ffmpeg")
    def test_runway_final_generates_master_movie_before_badge(self, run_ffmpeg, render_final, _which):
        self.create_upload(
            "best.mp4",
            GuestUpload.MediaType.VIDEO,
            category_code="emotional",
            duration=timedelta(seconds=8),
        )

        def create_badged_output(command):
            Path(command[-1]).write_bytes(b"badged-runway-final")

        def create_runway_output(_event, _uploads, _edit_decision_data, output_path):
            output_path.write_bytes(b"runway-final")
            return {"workflow_id": "workflow_123", "invocation_id": "invoke_123", "output_file": output_path.name}

        run_ffmpeg.side_effect = create_badged_output
        render_final.side_effect = create_runway_output

        movie = generate_event_movie(self.event)

        self.assertEqual(movie.status, GeneratedMovie.Status.COMPLETED)
        self.assertEqual(movie.render_provider, "runway_final")
        self.assertEqual(movie.edit_decision_data["runway_final"]["invocation_id"], "invoke_123")
        self.assertEqual(movie.edit_decision_data["badge"]["display_mode"], "full_movie")
        render_final.assert_called_once()
        self.assertEqual(run_ffmpeg.call_count, 1)

    @override_settings(
        MEMORA_RUNWAY_ENABLED=True,
        MEMORA_RUNWAY_API_SECRET="test-key",
        MEMORA_MOVIE_RENDER_PROVIDER="runway_final",
        MEMORA_RUNWAY_WORKFLOW_ID="workflow_123",
        MEMORA_RUNWAY_FALLBACK_TO_FFMPEG=True,
    )
    @patch("processing.services.shutil.which", return_value="ffmpeg")
    @patch("processing.services.render_final_movie_with_runway", side_effect=RuntimeError("workflow unavailable"))
    @patch("processing.services._run_ffmpeg")
    def test_runway_final_failure_falls_back_to_ffmpeg_movie(self, run_ffmpeg, render_final, _which):
        self.create_upload("photo.jpg", GuestUpload.MediaType.IMAGE, selected=True)

        def create_output(command):
            Path(command[-1]).write_bytes(b"movie-bytes")

        run_ffmpeg.side_effect = create_output

        movie = generate_event_movie(self.event)

        self.assertEqual(movie.status, GeneratedMovie.Status.COMPLETED)
        self.assertEqual(movie.render_provider, "ffmpeg")
        self.assertTrue(movie.edit_decision_data["runway_final"]["failed"])
        self.assertIn("workflow unavailable", movie.edit_decision_data["runway_final"]["error"])
        render_final.assert_called_once()
        self.assertGreaterEqual(run_ffmpeg.call_count, 3)

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

    @patch("processing.services._run_ffmpeg")
    def test_movie_image_clip_uses_ken_burns_zoompan_by_default(self, run_ffmpeg):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "clip.mp4"
            upload = SimpleNamespace(
                pk=125,
                media_file=SimpleUploadedFile("photo.jpg", make_test_image_bytes(), content_type="image/jpeg"),
                media_type=GuestUpload.MediaType.IMAGE,
                original_filename="photo.jpg",
            )

            def create_output(command):
                output_path.write_bytes(b"movie-bytes")

            run_ffmpeg.side_effect = create_output

            _build_movie_clip(upload, output_path, "ffmpeg")

        command = run_ffmpeg.call_args.args[0]
        video_filter = command[command.index("-filter_complex") + 1]
        self.assertIn("zoompan", video_filter)
        # Fond floute plein cadre plutot que des barres noires.
        self.assertIn("gblur", video_filter)
        self.assertNotIn("pad=", video_filter)

    @patch("processing.services._run_ffmpeg")
    @override_settings(MEMORA_MOVIE_KEN_BURNS_ENABLED=False)
    def test_movie_image_clip_skips_ken_burns_when_disabled(self, run_ffmpeg):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "clip.mp4"
            upload = SimpleNamespace(
                pk=126,
                media_file=SimpleUploadedFile("photo.jpg", make_test_image_bytes(), content_type="image/jpeg"),
                media_type=GuestUpload.MediaType.IMAGE,
                original_filename="photo.jpg",
            )

            def create_output(command):
                output_path.write_bytes(b"movie-bytes")

            run_ffmpeg.side_effect = create_output

            _build_movie_clip(upload, output_path, "ffmpeg")

        command = run_ffmpeg.call_args.args[0]
        video_filter = command[command.index("-filter_complex") + 1]
        self.assertNotIn("zoompan", video_filter)
        self.assertIn("gblur", video_filter)


@override_settings(MEMORA_MOVIE_INTRO_CARD_ENABLED=False)
class MovieVariantTests(TestCase):
    """Declinaisons integrale et teaser : elles ne doivent jamais casser le film heros.

    Le carton d'ouverture est desactive ici : ces tests portent sur la mecanique
    des declinaisons, il est couvert par TitleCardTests.
    """

    def test_variant_returns_none_without_uploads(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = services.build_movie_variant(
                SimpleNamespace(pk=1, title="Soiree"),
                [],
                Path(temp_dir),
                "ffmpeg",
                label="teaser",
            )
        self.assertIsNone(result)

    @patch("processing.services._apply_soundtrack_if_available")
    @patch("processing.services.choose_movie_soundtrack")
    @patch("processing.services._run_ffmpeg")
    @patch("processing.services._build_movie_clip")
    def test_variant_renders_at_requested_size(
        self, build_clip, run_ffmpeg, choose_soundtrack, apply_soundtrack
    ):
        build_clip.side_effect = (
            lambda upload, path, binary, width=None, height=None, beat_interval=None: path.write_bytes(b"clip")
        )
        apply_soundtrack.side_effect = lambda source, target, soundtrack, binary: source
        # Un tempo reel : sans ca le mock ferait remonter un MagicMock dans les
        # calculs de duree des cartons.
        choose_soundtrack.return_value = SimpleNamespace(
            mood="joyful_party",
            track_path=None,
            track_name="",
            beat_interval=0.5,
            first_beat_offset=0.0,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            result = services.build_movie_variant(
                SimpleNamespace(pk=7, title="Soiree Memora"),
                [SimpleNamespace(pk=1), SimpleNamespace(pk=2)],
                Path(temp_dir),
                "ffmpeg",
                label="teaser",
                width=1080,
                height=1920,
            )
            self.assertIsNotNone(result)

        # Le format demande est bien transmis a chaque clip.
        for call in build_clip.call_args_list:
            self.assertEqual(call.kwargs["width"], 1080)
            self.assertEqual(call.kwargs["height"], 1920)
        run_ffmpeg.assert_called()

    @patch("processing.services._run_ffmpeg")
    @patch("processing.services._build_movie_clip", side_effect=RuntimeError("clip casse"))
    def test_variant_survives_broken_clips(self, _build_clip, run_ffmpeg):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = services.build_movie_variant(
                SimpleNamespace(pk=9, title="Soiree"),
                [SimpleNamespace(pk=1)],
                Path(temp_dir),
                "ffmpeg",
                label="integrale",
            )
        self.assertIsNone(result)
        run_ffmpeg.assert_not_called()

    @override_settings(MEMORA_MOVIE_VARIANTS_ENABLED=False)
    @patch("processing.services.build_movie_variant")
    def test_variants_can_be_disabled(self, build_variant):
        services._render_movie_variants(
            SimpleNamespace(pk=1),
            SimpleNamespace(pk=1),
            Path("."),
            "ffmpeg",
        )
        build_variant.assert_not_called()


class TitleCardTests(TestCase):
    """Carton d'ouverture : un film doit commencer, pas demarrer sec sur une photo."""

    def test_card_is_rendered_at_the_requested_size(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = title_cards.build_title_card(
                Path(temp_dir) / "card.png", 1920, 1080, "Camille & Noe", "12/07/2026"
            )
            with Image.open(path) as image:
                self.assertEqual(image.size, (1920, 1080))

    def test_card_supports_the_vertical_teaser(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = title_cards.build_title_card(
                Path(temp_dir) / "card.png", 1080, 1920, "Camille & Noe", "12/07/2026"
            )
            with Image.open(path) as image:
                self.assertEqual(image.size, (1080, 1920))

    def test_intro_texts_prefer_the_couple_name(self):
        event = SimpleNamespace(
            couple_name="Camille & Noe", title="Mariage", event_date=date(2026, 7, 12)
        )
        title, subtitle = title_cards.event_intro_texts(event)
        self.assertEqual(title, "Camille & Noe")
        self.assertEqual(subtitle, "12/07/2026")

    def test_intro_texts_fall_back_to_the_event_title(self):
        event = SimpleNamespace(couple_name="", title="Gala Memora", event_date=None)
        title, subtitle = title_cards.event_intro_texts(event)
        self.assertEqual(title, "Gala Memora")
        self.assertEqual(subtitle, "")

    def test_a_font_is_always_resolved(self):
        self.assertIsNotNone(title_cards.resolve_title_font(64))

    @override_settings(MEMORA_MOVIE_INTRO_CARD_ENABLED=False)
    @patch("processing.services._run_ffmpeg")
    def test_intro_card_can_be_disabled(self, run_ffmpeg):
        result = services.build_intro_card_clip(
            SimpleNamespace(pk=1, couple_name="Camille", title="", event_date=None),
            Path("intro.mp4"),
            "ffmpeg",
        )
        self.assertIsNone(result)
        run_ffmpeg.assert_not_called()

    @patch("processing.services._run_ffmpeg")
    def test_no_card_without_a_name_to_show(self, run_ffmpeg):
        result = services.build_intro_card_clip(
            SimpleNamespace(pk=1, couple_name="", title="", event_date=None),
            Path("intro.mp4"),
            "ffmpeg",
        )
        self.assertIsNone(result)
        run_ffmpeg.assert_not_called()

    @patch("processing.services._run_ffmpeg", side_effect=RuntimeError("ffmpeg casse"))
    def test_a_failed_card_never_breaks_the_film(self, _run_ffmpeg):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = services.build_intro_card_clip(
                SimpleNamespace(pk=1, couple_name="Camille & Noe", title="", event_date=None),
                Path(temp_dir) / "intro.mp4",
                "ffmpeg",
            )
        self.assertIsNone(result)


class NarrativeOrderTests(TestCase):
    """Le film doit suivre le recit, pas le classement par score."""

    def _upload(self, code, media_type=GuestUpload.MediaType.VIDEO, sort_order=0):
        return SimpleNamespace(
            pk=id(code) % 10000 + sort_order,
            media_type=media_type,
            category=SimpleNamespace(code=code, sort_order=sort_order),
        )

    def test_moments_follow_the_story_arc(self):
        # Ordre volontairement chaotique, comme un tri par score.
        uploads = [
            self._upload("dancefloor"),
            self._upload("ceremony"),
            self._upload("cake"),
            self._upload("arrival"),
            self._upload("speech"),
        ]
        ordered = services._order_by_narrative_arc(uploads)
        codes = [upload.category.code for upload in ordered]
        self.assertEqual(codes, ["arrival", "ceremony", "speech", "cake", "dancefloor"])

    def test_custom_moments_follow_their_display_order(self):
        uploads = [
            self._upload("photo-booth", sort_order=42),
            self._upload("ceremony"),
        ]
        codes = [u.category.code for u in services._order_by_narrative_arc(uploads)]
        self.assertEqual(codes, ["ceremony", "photo-booth"])

    def test_photos_and_videos_stay_interleaved_inside_a_moment(self):
        uploads = [
            self._upload("ceremony", GuestUpload.MediaType.VIDEO),
            self._upload("ceremony", GuestUpload.MediaType.VIDEO),
            self._upload("ceremony", GuestUpload.MediaType.IMAGE),
        ]
        ordered = services._order_by_narrative_arc(uploads)
        self.assertEqual(len(ordered), 3)
        # Le tissage evite d'enchainer toutes les videos puis toutes les photos.
        self.assertIn(GuestUpload.MediaType.IMAGE, [u.media_type for u in ordered])

    @override_settings(MEMORA_MOVIE_NARRATIVE_ORDER_ENABLED=False)
    def test_ordering_can_be_disabled(self):
        uploads = [self._upload("dancefloor"), self._upload("arrival")]
        codes = [u.category.code for u in services._order_by_narrative_arc(uploads)]
        self.assertEqual(codes, ["dancefloor", "arrival"])

    def test_no_media_is_lost_in_reordering(self):
        uploads = [
            self._upload("dancefloor"),
            self._upload("ceremony", GuestUpload.MediaType.IMAGE),
            self._upload("other"),
            self._upload("speech"),
        ]
        self.assertEqual(len(services._order_by_narrative_arc(uploads)), len(uploads))


class BeatSyncTests(TestCase):
    """Coupes calees sur le tempo : c'est ce qui fait passer du diaporama au montage."""

    def test_durations_snap_to_whole_beats(self):
        beat = 60.0 / 120.0  # 0.5 s
        self.assertAlmostEqual(services.snap_duration_to_beat(3.0, beat), 3.0, places=3)
        self.assertAlmostEqual(services.snap_duration_to_beat(2.8, beat), 3.0, places=3)
        self.assertAlmostEqual(services.snap_duration_to_beat(3.3, beat), 3.5, places=3)

    def test_snapping_is_a_no_op_without_tempo(self):
        self.assertEqual(services.snap_duration_to_beat(3.7, 0), 3.7)
        self.assertEqual(services.snap_duration_to_beat(3.7, None), 3.7)

    def test_minimum_length_is_respected(self):
        beat = 60.0 / 176.9
        self.assertGreaterEqual(services.snap_duration_to_beat(0.05, beat), 2 * beat - 0.001)

    def test_cumulated_cuts_stay_on_the_musical_grid(self):
        beat = 60.0 / 85.9
        total = sum(services.snap_duration_to_beat(value, beat) for value in (3, 3, 7, 3, 9, 3))
        # Le cumul doit rester un multiple entier du temps : sinon les coupes derivent.
        self.assertAlmostEqual(total / beat, round(total / beat), places=1)

    def test_known_tracks_expose_their_tempo(self):
        for name, (bpm, offset) in soundtrack_module.TRACK_TEMPOS.items():
            self.assertGreater(bpm, 0, name)
            self.assertGreaterEqual(offset, 0, name)

    @patch("processing.services._media_file_has_audio", return_value=True)
    @patch("processing.services._run_ffmpeg")
    def test_music_starts_on_its_first_beat(self, run_ffmpeg, _has_audio):
        choice = soundtrack_module.SoundtrackChoice(
            mood="romantic_cinematic",
            track_path=Path("track.mp3"),
            reason="test",
            bpm=85.9,
            first_beat_offset=1.25,
        )
        services._apply_soundtrack_if_available(
            Path("in.mp4"), Path("out.mp4"), choice, "ffmpeg"
        )
        command = run_ffmpeg.call_args.args[0]
        self.assertIn("-ss", command)
        self.assertEqual(command[command.index("-ss") + 1], "1.25")

    @patch("processing.services._media_file_has_audio", return_value=True)
    @patch("processing.services._run_ffmpeg")
    def test_no_seek_when_track_starts_on_the_beat(self, run_ffmpeg, _has_audio):
        choice = soundtrack_module.SoundtrackChoice(
            mood="joyful_party",
            track_path=Path("track.mp3"),
            reason="test",
            bpm=120.3,
            first_beat_offset=0.0,
        )
        services._apply_soundtrack_if_available(
            Path("in.mp4"), Path("out.mp4"), choice, "ffmpeg"
        )
        self.assertNotIn("-ss", run_ffmpeg.call_args.args[0])


class GeneratedMovieAdminActionTests(TestCase):
    def setUp(self):
        self.organizer = get_user_model().objects.create_user(
            username="admin-organizer",
            password="secret",
        )
        self.superuser = get_user_model().objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="secret",
        )
        self.event_type = EventType.objects.get(code="wedding")
        self.event = Event.objects.create(
            organizer=self.organizer,
            title="Mariage Admin",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
        )

    def test_regenerate_action_resets_completed_movie_to_pending(self):
        movie = GeneratedMovie.objects.create(
            event=self.event,
            status=GeneratedMovie.Status.COMPLETED,
            final_file="events/x/movies/final.mp4",
            error_logs="ancienne erreur",
            progress_percent=100,
            progress_message="Termine.",
        )
        self.client.login(username="admin", password="secret")

        self.client.post(
            reverse("admin:processing_generatedmovie_changelist"),
            {"action": "regenerate_movies", "_selected_action": [movie.pk]},
        )

        movie.refresh_from_db()
        self.assertEqual(movie.status, GeneratedMovie.Status.PENDING)
        self.assertEqual(movie.error_logs, "")
        self.assertEqual(movie.progress_percent, 0)
        self.assertEqual(movie.progress_message, "")

    def test_regenerate_action_skips_processing_movie(self):
        movie = GeneratedMovie.objects.create(
            event=self.event,
            status=GeneratedMovie.Status.PROCESSING,
            progress_percent=42,
        )
        self.client.login(username="admin", password="secret")

        self.client.post(
            reverse("admin:processing_generatedmovie_changelist"),
            {"action": "regenerate_movies", "_selected_action": [movie.pk]},
        )

        movie.refresh_from_db()
        self.assertEqual(movie.status, GeneratedMovie.Status.PROCESSING)
        self.assertEqual(movie.progress_percent, 42)


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
        event.mark_paid(provider="test")
        event.save(update_fields=["payment_status", "paid_at", "payment_provider"])
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
    @patch("processing.management.commands.generate_scheduled_movies.create_event_movie_job")
    def test_failed_movie_is_not_retried_automatically(self, create_movie_job):
        event = self.create_event_with_video(timezone.localdate() - timedelta(days=1))
        GeneratedMovie.objects.create(event=event, status=GeneratedMovie.Status.FAILED)

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

    @patch("processing.management.commands.process_pending_movies.get_pending_movie_jobs")
    @patch("processing.management.commands.process_pending_movies.process_generated_movie")
    def test_can_include_processing_movies(self, process_generated_movie, get_pending_movie_jobs):
        movie = GeneratedMovie.objects.create(event=self.event, status=GeneratedMovie.Status.PROCESSING)
        get_pending_movie_jobs.return_value = [movie]
        process_generated_movie.return_value = movie

        call_command("process_pending_movies", "--include-processing")

        get_pending_movie_jobs.assert_called_once_with(limit=5, include_processing=True)
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


class ProcessEventMovieCommandTests(TestCase):
    def setUp(self):
        organizer = get_user_model().objects.create_user(
            username="organizer-event-movie",
            password="secret",
        )
        event_type = EventType.objects.get(code="wedding")
        self.event = Event.objects.create(
            organizer=organizer,
            title="Film Evenement",
            event_type=event_type,
            event_date=date(2026, 7, 8),
        )

    @patch("processing.management.commands.process_event_movie.process_generated_movie")
    def test_processes_event_pending_movie(self, process_generated_movie):
        movie = GeneratedMovie.objects.create(event=self.event, status=GeneratedMovie.Status.PENDING)
        process_generated_movie.return_value = movie

        call_command("process_event_movie", self.event.pk)

        process_generated_movie.assert_called_once_with(movie)

    @patch("processing.management.commands.process_event_movie.process_generated_movie")
    def test_can_resume_processing_movie_when_requested(self, process_generated_movie):
        movie = GeneratedMovie.objects.create(event=self.event, status=GeneratedMovie.Status.PROCESSING)
        process_generated_movie.return_value = movie

        call_command("process_event_movie", self.event.pk, "--include-processing")

        process_generated_movie.assert_called_once_with(movie)

    @patch("processing.management.commands.process_event_movie.process_generated_movie")
    def test_dry_run_does_not_process_event_movie(self, process_generated_movie):
        GeneratedMovie.objects.create(event=self.event, status=GeneratedMovie.Status.PENDING)
        output = StringIO()

        call_command("process_event_movie", self.event.pk, "--dry-run", stdout=output)

        process_generated_movie.assert_not_called()
        self.assertIn("[dry-run]", output.getvalue())

    @patch("processing.management.commands.process_event_movie.process_generated_movie")
    def test_marks_movie_failed_when_processing_crashes(self, process_generated_movie):
        movie = GeneratedMovie.objects.create(event=self.event, status=GeneratedMovie.Status.PROCESSING)
        process_generated_movie.side_effect = RuntimeError("ffmpeg boom")

        call_command("process_event_movie", self.event.pk, "--include-processing")

        movie.refresh_from_db()
        self.assertEqual(movie.status, GeneratedMovie.Status.FAILED)
        self.assertIn("ffmpeg boom", movie.error_logs)


class NotifyReadyMoviesCommandTests(TestCase):
    def setUp(self):
        self.organizer = get_user_model().objects.create_user(
            username="organizer-ready",
            email="organizer-ready@example.com",
            password="secret",
        )
        self.event_type = EventType.objects.get(code="wedding")
        self.event = Event.objects.create(
            organizer=self.organizer,
            title="Film Pret",
            event_type=self.event_type,
            event_date=date(2026, 7, 8),
        )

    @patch("processing.management.commands.notify_ready_movies.notify_generated_movie_ready")
    def test_notify_ready_movies_dry_run_does_not_notify(self, notify_ready):
        GeneratedMovie.objects.create(
            event=self.event,
            status=GeneratedMovie.Status.COMPLETED,
            final_file="events/film/movies/memora.mp4",
            generated_at=timezone.now(),
        )
        output = StringIO()

        call_command("notify_ready_movies", "--dry-run", stdout=output)

        notify_ready.assert_not_called()
        self.assertIn("[dry-run]", output.getvalue())

    @patch("processing.management.commands.notify_ready_movies.notify_generated_movie_ready")
    def test_notify_ready_movies_notifies_completed_movies(self, notify_ready):
        movie = GeneratedMovie.objects.create(
            event=self.event,
            status=GeneratedMovie.Status.COMPLETED,
            final_file="events/film/movies/memora.mp4",
            generated_at=timezone.now(),
        )
        notify_ready.return_value = True

        call_command("notify_ready_movies")

        notify_ready.assert_called_once_with(movie)


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
