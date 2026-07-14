from datetime import datetime, time, timedelta
from io import BytesIO
import logging
from pathlib import Path
import shutil
import subprocess
import tempfile
from zipfile import ZIP_DEFLATED, ZipFile

from django.conf import settings
from django.core.files.base import File
from django.core.mail import send_mail
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

from uploads.models import GuestUpload

from .analysis import analyze_event_media
from .models import GeneratedMovie, MediaAnalysis
from .runway import build_runway_montage_payload, enhance_clip_with_runway, runway_is_ready
from .soundtrack import build_edit_decision_data, choose_movie_soundtrack


logger = logging.getLogger(__name__)


DEFAULT_ZIP_CATEGORY_FOLDERS = {
    "ceremony": "01_Ceremonie",
    "arrival": "02_Arrivee",
    "cocktail": "03_Cocktail",
    "reception": "04_Reception",
    "speech": "05_Discours",
    "dancefloor": "06_Piste_de_danse",
    "cake": "07_Gateau",
    "funny": "08_Moment_drole",
    "emotional": "09_Moment_emouvant",
    "other": "10_Autre",
}

MOVIE_CATEGORY_SCORE_BOOSTS = {
    "ceremony": 16,
    "speech": 14,
    "dancefloor": 18,
    "cake": 12,
    "funny": 18,
    "emotional": 20,
}

MOVIE_PHOTO_CATEGORY_SCORE_BOOSTS = {
    "ceremony": 10,
    "cake": 8,
    "emotional": 14,
    "funny": 10,
    "reception": 6,
}


def build_event_zip(event):
    root_name = f"Memora_{_clean_name(event.title)}"
    buffer = BytesIO()

    uploads = (
        event.guest_uploads.filter(
            is_deleted=False,
            moderation_status="approved",
        )
        .select_related("category")
        .order_by("category__sort_order", "uploaded_at", "pk")
    )

    used_paths = set()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        categories = list(event.upload_categories.filter(is_active=True).order_by("sort_order", "label"))
        category_folders = {
            category.id: _category_folder_name(category)
            for category in categories
        }

        for folder_name in category_folders.values():
            archive.writestr(f"{root_name}/{folder_name}/", "")

        for upload in uploads:
            if not upload.media_file:
                continue

            folder_name = category_folders.get(upload.category_id, _category_folder_name(upload.category))
            archive_name = _build_archive_name(upload)
            archive_path = f"{root_name}/{folder_name}/{archive_name}"
            archive_path = _dedupe_path(archive_path, used_paths)

            try:
                upload.media_file.open("rb")
                archive.writestr(archive_path, upload.media_file.read())
            finally:
                upload.media_file.close()

    buffer.seek(0)
    filename = f"{root_name}.zip"
    return filename, buffer.getvalue()


def get_movie_candidate_uploads(event):
    uploads = list(
        event.guest_uploads.filter(
            is_deleted=False,
            moderation_status=GuestUpload.ModerationStatus.APPROVED,
        )
        .select_related("category")
        .order_by("uploaded_at", "pk")
    )

    videos = _sort_movie_candidates(
        upload for upload in uploads if upload.media_type == GuestUpload.MediaType.VIDEO
    )
    photos = _sort_movie_candidates(
        upload for upload in uploads if upload.media_type == GuestUpload.MediaType.IMAGE
    )

    if not videos:
        return _select_until_duration_limit(photos, settings.MEMORA_MOVIE_MAX_DURATION_SECONDS)
    if not photos:
        return _select_until_duration_limit(videos, settings.MEMORA_MOVIE_MAX_DURATION_SECONDS)

    selected_videos, reserved_photo_seconds = _select_videos_with_photo_reserve(videos, photos)
    selected_photos = _select_photos_for_mixed_movie(
        photos,
        selected_videos,
        reserved_photo_seconds,
    )
    selected_videos = _fill_remaining_duration_with_videos(videos, selected_videos, selected_photos)
    return _weave_photos_between_videos(selected_videos, selected_photos)


def score_movie_candidate(upload):
    try:
        analysis = upload.analysis
    except MediaAnalysis.DoesNotExist:
        analysis = None

    if analysis and analysis.status == MediaAnalysis.Status.COMPLETED:
        score = analysis.movie_score
        if upload.media_type == GuestUpload.MediaType.VIDEO:
            score += 18
        else:
            score += MOVIE_PHOTO_CATEGORY_SCORE_BOOSTS.get(upload.category.code, 0)
        if upload.is_selected_for_movie:
            score += 5
        return score

    score = 100 if upload.media_type == GuestUpload.MediaType.VIDEO else 35
    score += MOVIE_CATEGORY_SCORE_BOOSTS.get(upload.category.code, 0)

    if upload.is_selected_for_movie:
        score += 8

    if upload.file_size:
        score += min(upload.file_size / (8 * 1024 * 1024), 10)

    if upload.duration:
        seconds = upload.duration.total_seconds()
        if 3 <= seconds <= settings.MEMORA_MAX_VIDEO_UPLOAD_DURATION_SECONDS:
            score += 8
        elif seconds < 3:
            score -= 10

    return score


def _sort_movie_candidates(uploads):
    candidates = list(uploads)
    candidates.sort(
        key=lambda upload: (
            score_movie_candidate(upload),
            upload.uploaded_at,
            upload.pk,
        ),
        reverse=True,
    )
    return candidates


def _select_until_duration_limit(candidates, max_duration, max_count=None):
    selected_uploads = []
    total_duration = 0
    for upload in candidates:
        if max_count is not None and len(selected_uploads) >= max_count:
            break
        estimated_duration = _estimated_movie_clip_duration(upload)
        if total_duration + estimated_duration > max_duration:
            continue
        selected_uploads.append(upload)
        total_duration += estimated_duration
        if total_duration >= max_duration:
            break
    return selected_uploads


def _select_videos_with_photo_reserve(videos, photos):
    max_duration = settings.MEMORA_MOVIE_MAX_DURATION_SECONDS
    target_photo_seconds = int(max_duration * settings.MEMORA_MOVIE_PHOTO_TARGET_RATIO)
    min_photo_seconds = min(
        len(photos),
        settings.MEMORA_MOVIE_MIN_PHOTO_COUNT_WITH_VIDEOS,
    ) * settings.MEMORA_MOVIE_IMAGE_DURATION_SECONDS
    reserved_photo_seconds = min(max(target_photo_seconds, min_photo_seconds), max_duration)
    video_budget = max(max_duration - reserved_photo_seconds, 0)

    selected_videos = _select_until_duration_limit(videos, video_budget)
    if not selected_videos:
        selected_videos = _select_until_duration_limit(videos, max_duration)
        reserved_photo_seconds = max_duration - sum(_estimated_movie_clip_duration(upload) for upload in selected_videos)

    return selected_videos, reserved_photo_seconds


def _select_photos_for_mixed_movie(photos, selected_videos, reserved_photo_seconds):
    used_video_seconds = sum(_estimated_movie_clip_duration(upload) for upload in selected_videos)
    remaining_duration = max(settings.MEMORA_MOVIE_MAX_DURATION_SECONDS - used_video_seconds, 0)
    photo_budget = min(reserved_photo_seconds, remaining_duration)
    max_photo_count = max(
        len(selected_videos),
        settings.MEMORA_MOVIE_MIN_PHOTO_COUNT_WITH_VIDEOS,
    )
    return _select_until_duration_limit(photos, photo_budget, max_count=max_photo_count)


def _fill_remaining_duration_with_videos(videos, selected_videos, selected_photos):
    selected_ids = {upload.pk for upload in selected_videos}
    used_duration = sum(
        _estimated_movie_clip_duration(upload)
        for upload in [*selected_videos, *selected_photos]
    )
    remaining_duration = max(settings.MEMORA_MOVIE_MAX_DURATION_SECONDS - used_duration, 0)

    additional_videos = _select_until_duration_limit(
        [upload for upload in videos if upload.pk not in selected_ids],
        remaining_duration,
    )
    return [*selected_videos, *additional_videos]


def _weave_photos_between_videos(videos, photos):
    if not photos:
        return videos

    interval = max(settings.MEMORA_MOVIE_MAX_CONSECUTIVE_VIDEOS_BEFORE_PHOTO, 1)
    photo_slots = {index: [] for index in range(1, len(videos) + 1)}
    for photo_index, photo in enumerate(photos):
        slot = 1 + (photo_index * len(videos)) // len(photos)
        photo_slots[slot].append(photo)

    selected = []
    consecutive_videos = 0
    pending_photos = []
    for index, video in enumerate(videos, start=1):
        selected.append(video)
        consecutive_videos += 1
        pending_photos.extend(photo_slots[index])
        if pending_photos and (consecutive_videos >= interval or index == len(videos)):
            selected.extend(pending_photos)
            pending_photos = []
            consecutive_videos = 0

    return selected


def get_event_movie_schedule_at(event):
    scheduled_date = event.event_date + timedelta(days=1)
    scheduled_time = time(hour=settings.MEMORA_MOVIE_AUTOGENERATE_HOUR)
    scheduled_at = datetime.combine(scheduled_date, scheduled_time)
    return timezone.make_aware(scheduled_at, timezone.get_current_timezone())


def get_scheduled_movie_events(now=None):
    from events.models import Event

    now = timezone.localtime(now or timezone.now())
    events = Event.objects.filter(
        is_active=True,
        payment_status=Event.PaymentStatus.PAID,
    ).order_by("event_date", "pk")

    scheduled_events = []
    for event in events:
        if get_event_movie_schedule_at(event) > now:
            continue

        has_existing_movie = event.generated_movies.exists()
        if has_existing_movie:
            continue

        if not get_movie_candidate_uploads(event):
            continue

        scheduled_events.append(event)

    return scheduled_events


def create_event_movie_job(event, allow_retry=False):
    if not event.is_paid:
        raise ValueError("Le film souvenir ne peut pas etre genere avant activation de l'evenement.")

    existing_job = (
        event.generated_movies.filter(
            status__in=[
                GeneratedMovie.Status.PENDING,
                GeneratedMovie.Status.PROCESSING,
                GeneratedMovie.Status.COMPLETED,
            ]
        )
        .order_by("-created_at")
        .first()
    )
    if existing_job:
        return existing_job

    failed_job = (
        event.generated_movies.filter(status=GeneratedMovie.Status.FAILED)
        .order_by("-created_at")
        .first()
    )
    if failed_job and not allow_retry:
        return failed_job

    return GeneratedMovie.objects.create(
        event=event,
        status=GeneratedMovie.Status.PENDING,
        progress_percent=5,
        progress_message="Film planifie. Memora attend le worker de generation.",
    )


def get_pending_movie_jobs(limit=None, include_processing=False):
    stale_processing_before = timezone.now() - timedelta(
        minutes=settings.MEMORA_MOVIE_PROCESSING_STALE_MINUTES
    )
    processing_filter = Q(status=GeneratedMovie.Status.PROCESSING)
    if not include_processing:
        processing_filter &= Q(updated_at__lte=stale_processing_before)

    queryset = (
        GeneratedMovie.objects.filter(
            Q(status=GeneratedMovie.Status.PENDING)
            | processing_filter
        )
        .select_related("event")
        .order_by("updated_at", "created_at", "pk")
    )
    if limit:
        return list(queryset[:limit])
    return list(queryset)


def process_pending_movie_jobs(limit=None, include_processing=False):
    processed_movies = []
    for movie in get_pending_movie_jobs(limit=limit, include_processing=include_processing):
        processed_movies.append(process_generated_movie(movie))
    return processed_movies


def generate_event_movie(event):
    movie = create_event_movie_job(event, allow_retry=True)
    return process_generated_movie(movie)


def process_generated_movie(movie):
    movie.refresh_from_db()
    if movie.status not in {GeneratedMovie.Status.PENDING, GeneratedMovie.Status.PROCESSING}:
        logger.info("Movie skipped movie=%s event=%s status=%s", movie.pk, movie.event_id, movie.status)
        return movie

    event = movie.event
    logger.info("Movie processing started movie=%s event=%s", movie.pk, event.pk)
    try:
        _update_movie_progress(movie, 10, "Analyse des souvenirs recus.")
        analyze_event_media(event)
        _update_movie_progress(movie, 18, "Selection automatique des meilleurs moments.")
        uploads = list(get_movie_candidate_uploads(event))
    except Exception as exc:
        movie.status = GeneratedMovie.Status.FAILED
        movie.error_logs = str(exc)
        movie.progress_message = "La selection automatique a echoue."
        movie.save(update_fields=["status", "error_logs", "progress_message", "updated_at"])
        logger.exception("Movie automatic selection failed movie=%s event=%s", movie.pk, event.pk)
        return movie

    if not uploads:
        movie.status = GeneratedMovie.Status.FAILED
        movie.error_logs = "Aucun media accepte disponible pour generer le film souvenir."
        movie.progress_message = "Aucun souvenir valide disponible pour le film."
        movie.save(update_fields=["status", "error_logs", "progress_message", "updated_at"])
        logger.warning("Movie failed without valid media movie=%s event=%s", movie.pk, event.pk)
        return movie

    ffmpeg_binary = settings.MEMORA_FFMPEG_BINARY
    if shutil.which(ffmpeg_binary) is None and not Path(ffmpeg_binary).exists():
        movie.status = GeneratedMovie.Status.FAILED
        movie.error_logs = f"FFmpeg introuvable: {ffmpeg_binary}"
        movie.progress_message = "La generation video n'est pas disponible pour le moment."
        movie.save(update_fields=["status", "error_logs", "progress_message", "updated_at"])
        logger.error("Movie failed because FFmpeg is missing movie=%s event=%s binary=%s", movie.pk, event.pk, ffmpeg_binary)
        return movie

    movie.status = GeneratedMovie.Status.PROCESSING
    movie.progress_percent = max(movie.progress_percent, 22)
    movie.progress_message = "Preparation du plan de montage."
    soundtrack = choose_movie_soundtrack(event, uploads)
    edit_decision_data = build_edit_decision_data(event, uploads, soundtrack)
    runway_ready = runway_is_ready()
    edit_decision_data["runway"] = {
        "ready": runway_ready,
        "payload": build_runway_montage_payload(event, uploads, edit_decision_data),
    }
    movie.render_provider = "ffmpeg"
    movie.music_mood = soundtrack.mood
    movie.music_track = soundtrack.track_name
    movie.edit_decision_data = edit_decision_data
    movie.save(
        update_fields=[
            "status",
            "progress_percent",
            "progress_message",
            "render_provider",
            "music_mood",
            "music_track",
            "edit_decision_data",
            "updated_at",
        ]
    )

    try:
        with tempfile.TemporaryDirectory(prefix="memora_movie_") as temp_dir:
            temp_path = Path(temp_dir)
            clip_paths = []
            total_duration = 0
            runway_enhancements = []
            runway_enhanced_count = 0
            clip_count = max(len(uploads), 1)
            for index, upload in enumerate(uploads, start=1):
                clip_progress = 24 + int((index - 1) * 42 / clip_count)
                _update_movie_progress(
                    movie,
                    clip_progress,
                    f"Preparation du clip {index}/{clip_count}.",
                )
                clip_path = temp_path / f"clip_{index:04d}.mp4"
                _build_movie_clip(upload, clip_path, ffmpeg_binary)
                if _should_enhance_clip_with_runway(upload, runway_enhanced_count):
                    _update_movie_progress(
                        movie,
                        min(clip_progress + 3, 68),
                        f"Amelioration Runway du clip {index}/{clip_count}.",
                    )
                    runway_clip_path = temp_path / f"clip_{index:04d}_runway.mp4"
                    try:
                        logger.info(
                            "Runway enhancement started movie=%s event=%s upload=%s",
                            movie.pk,
                            event.pk,
                            upload.pk,
                        )
                        enhancement = enhance_clip_with_runway(
                            clip_path,
                            runway_clip_path,
                            prompt_text=edit_decision_data["runway"]["payload"]["style_prompt"],
                        )
                        enhancement.update(
                            {
                                "upload_id": upload.pk,
                                "filename": upload.original_filename,
                                "source_clip": clip_path.name,
                            }
                        )
                        runway_enhancements.append(enhancement)
                        logger.info(
                            "Runway enhancement completed movie=%s event=%s upload=%s task=%s",
                            movie.pk,
                            event.pk,
                            upload.pk,
                            enhancement.get("task_id", ""),
                        )
                        clip_path = runway_clip_path
                        runway_enhanced_count += 1
                    except Exception as exc:
                        logger.warning(
                            "Runway enhancement failed movie=%s event=%s upload=%s error=%s",
                            movie.pk,
                            event.pk,
                            upload.pk,
                            exc,
                        )
                        runway_enhancements.append(
                            {
                                "upload_id": upload.pk,
                                "filename": upload.original_filename,
                                "source_clip": clip_path.name,
                                "failed": True,
                                "error": str(exc),
                                "fallback": settings.MEMORA_RUNWAY_FALLBACK_TO_FFMPEG,
                            }
                        )
                        if not settings.MEMORA_RUNWAY_FALLBACK_TO_FFMPEG:
                            raise
                clip_paths.append(clip_path)
                total_duration += _estimated_movie_clip_duration(upload)

            _update_movie_progress(movie, 68, "Assemblage des clips selectionnes.")
            movie.edit_decision_data["runway"]["enhancements"] = runway_enhancements
            if runway_enhanced_count:
                movie.render_provider = "runway+ffmpeg"

            concat_file = temp_path / "clips.txt"
            concat_file.write_text(
                "".join(f"file '{path.as_posix()}'\n" for path in clip_paths),
                encoding="utf-8",
            )
            concat_output_path = temp_path / f"memora_{_clean_name(event.title)}_base.mp4"
            _run_ffmpeg(
                [
                    ffmpeg_binary,
                    "-y",
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    str(concat_file),
                    "-c",
                    "copy",
                    str(concat_output_path),
                ]
            )

            _update_movie_progress(movie, 78, "Mixage de la musique et des voix.")
            soundtrack_output_path = temp_path / f"memora_{_clean_name(event.title)}_soundtrack.mp4"
            soundtrack_output_path = _apply_soundtrack_if_available(
                concat_output_path,
                soundtrack_output_path,
                soundtrack,
                ffmpeg_binary,
            )
            output_path = temp_path / f"memora_{_clean_name(event.title)}.mp4"
            badge_data = {
                "enabled": settings.MEMORA_MOVIE_BADGE_ENABLED,
                "display_name": _event_display_name(event),
                "duration_seconds": None,
                "display_mode": "full_movie",
                "applied": False,
            }
            _update_movie_progress(movie, 88, "Ajout du badge premium de l'evenement.")
            try:
                final_output_path = _apply_event_badge(
                    soundtrack_output_path,
                    output_path,
                    event,
                    ffmpeg_binary,
                    temp_path,
                )
                badge_data["applied"] = final_output_path == output_path
            except Exception as exc:
                final_output_path = soundtrack_output_path
                badge_data["error"] = str(exc)
            movie.edit_decision_data["badge"] = badge_data

            _update_movie_progress(movie, 94, "Enregistrement de la video finale.")
            with final_output_path.open("rb") as output_file:
                movie.final_file.save(final_output_path.name, File(output_file), save=False)

        movie.status = GeneratedMovie.Status.COMPLETED
        movie.progress_percent = 100
        movie.progress_message = "Votre film souvenir est pret."
        movie.generated_at = timezone.now()
        movie.duration = timedelta(seconds=min(total_duration, settings.MEMORA_MOVIE_MAX_DURATION_SECONDS))
        movie.error_logs = ""
        movie.save(
            update_fields=[
                "final_file",
                "status",
                "progress_percent",
                "progress_message",
                "generated_at",
                "duration",
                "render_provider",
                "music_mood",
                "music_track",
                "edit_decision_data",
                "error_logs",
                "updated_at",
            ]
        )
        if event.is_active:
            event.is_active = False
            event.save(update_fields=["is_active", "updated_at"])
            logger.info("Guest collection closed after movie completion event=%s movie=%s", event.pk, movie.pk)
        logger.info("Movie processing completed movie=%s event=%s", movie.pk, event.pk)
        notify_generated_movie_ready(movie)
    except Exception as exc:
        movie.status = GeneratedMovie.Status.FAILED
        movie.error_logs = str(exc)
        movie.progress_message = "La generation a ete interrompue. Vous pouvez relancer le film."
        movie.save(update_fields=["status", "error_logs", "progress_message", "updated_at"])
        logger.exception("Movie processing failed movie=%s event=%s", movie.pk, event.pk)

    return movie


def notify_generated_movie_ready(movie):
    movie.refresh_from_db()
    if (
        movie.status != GeneratedMovie.Status.COMPLETED
        or movie.organizer_notified_at
        or not movie.event.organizer.email
    ):
        logger.info("Ready movie notification skipped movie=%s event=%s", movie.pk, movie.event_id)
        return False

    dashboard_url = _event_dashboard_url(movie.event)
    message = (
        f"Bonjour,\n\n"
        f"Votre film souvenir Memora pour \"{movie.event.title}\" est pret.\n\n"
        f"Vous pouvez le regarder et le telecharger ici :\n{dashboard_url}\n\n"
        "Merci d'avoir confie vos souvenirs a Memora."
    )
    try:
        send_mail(
            subject=f"Votre film souvenir Memora est pret - {movie.event.title}",
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[movie.event.organizer.email],
            fail_silently=False,
        )
    except Exception as exc:
        logger.exception("Ready movie notification failed movie=%s event=%s", movie.pk, movie.event_id)
        movie.edit_decision_data["notification"] = {
            "email_ready_failed": True,
            "error": str(exc),
        }
        movie.save(update_fields=["edit_decision_data", "updated_at"])
        return False

    movie.organizer_notified_at = timezone.now()
    movie.edit_decision_data["notification"] = {
        "email_ready_sent": True,
        "sent_at": movie.organizer_notified_at.isoformat(),
    }
    movie.save(update_fields=["organizer_notified_at", "edit_decision_data", "updated_at"])
    logger.info("Ready movie notification sent movie=%s event=%s", movie.pk, movie.event_id)
    return True


def _event_dashboard_url(event):
    path = reverse("events:detail", kwargs={"pk": event.pk})
    base_url = settings.MEMORA_PUBLIC_BASE_URL.rstrip("/")
    if not base_url:
        return path
    return f"{base_url}{path}"


def _update_movie_progress(movie, percent, message):
    movie.progress_percent = max(0, min(int(percent), 100))
    movie.progress_message = message[:160]
    movie.save(update_fields=["progress_percent", "progress_message", "updated_at"])


def _should_enhance_clip_with_runway(upload, enhanced_count):
    return (
        runway_is_ready()
        and upload.media_type == GuestUpload.MediaType.VIDEO
        and enhanced_count < settings.MEMORA_RUNWAY_MAX_ENHANCED_CLIPS
    )


def _clean_name(value):
    cleaned = slugify(value).replace("-", "_")
    return cleaned or "Evenement"


def _estimated_movie_clip_duration(upload):
    if upload.media_type == GuestUpload.MediaType.IMAGE:
        return settings.MEMORA_MOVIE_IMAGE_DURATION_SECONDS

    if upload.duration:
        return min(
            int(upload.duration.total_seconds()),
            settings.MEMORA_MOVIE_VIDEO_MAX_SECONDS,
        )

    return settings.MEMORA_MOVIE_VIDEO_MAX_SECONDS


def _build_movie_clip(upload, output_path, ffmpeg_binary):
    if not upload.media_file:
        raise ValueError(f"Media sans fichier: {upload.pk}")

    input_path = _copy_media_to_temporary_file(upload, output_path.parent)
    try:
        video_filter = (
            f"scale={settings.MEMORA_MOVIE_WIDTH}:{settings.MEMORA_MOVIE_HEIGHT}:"
            "force_original_aspect_ratio=decrease,"
            f"pad={settings.MEMORA_MOVIE_WIDTH}:{settings.MEMORA_MOVIE_HEIGHT}:(ow-iw)/2:(oh-ih)/2,"
            "fps=30,format=yuv420p"
        )

        if upload.media_type == GuestUpload.MediaType.IMAGE:
            clip_duration = str(settings.MEMORA_MOVIE_IMAGE_DURATION_SECONDS)
            command = [
                ffmpeg_binary,
                "-y",
                "-loop",
                "1",
                "-t",
                clip_duration,
                "-i",
                str(input_path),
                "-f",
                "lavfi",
                "-t",
                clip_duration,
                "-i",
                "anullsrc=channel_layout=stereo:sample_rate=48000",
                "-vf",
                video_filter,
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:v",
                settings.MEMORA_MOVIE_VIDEO_ENCODER,
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-ar",
                "48000",
                "-ac",
                "2",
                "-shortest",
                "-movflags",
                "+faststart",
                str(output_path),
            ]
        else:
            clip_duration = str(settings.MEMORA_MOVIE_VIDEO_MAX_SECONDS)
            if _media_file_has_audio(input_path):
                command = [
                    ffmpeg_binary,
                    "-y",
                    "-i",
                    str(input_path),
                    "-t",
                    clip_duration,
                    "-vf",
                    video_filter,
                    "-map",
                    "0:v:0",
                    "-map",
                    "0:a:0",
                    "-c:v",
                    settings.MEMORA_MOVIE_VIDEO_ENCODER,
                    "-c:a",
                    "aac",
                    "-b:a",
                    "128k",
                    "-ar",
                    "48000",
                    "-ac",
                    "2",
                    "-movflags",
                    "+faststart",
                    str(output_path),
                ]
            else:
                command = [
                    ffmpeg_binary,
                    "-y",
                    "-i",
                    str(input_path),
                    "-f",
                    "lavfi",
                    "-t",
                    clip_duration,
                    "-i",
                    "anullsrc=channel_layout=stereo:sample_rate=48000",
                    "-t",
                    clip_duration,
                    "-vf",
                    video_filter,
                    "-map",
                    "0:v:0",
                    "-map",
                    "1:a:0",
                    "-c:v",
                    settings.MEMORA_MOVIE_VIDEO_ENCODER,
                    "-c:a",
                    "aac",
                    "-b:a",
                    "128k",
                    "-ar",
                    "48000",
                    "-ac",
                    "2",
                    "-shortest",
                    "-movflags",
                    "+faststart",
                    str(output_path),
                ]

        _run_ffmpeg(command)
    finally:
        input_path.unlink(missing_ok=True)


def _copy_media_to_temporary_file(upload, directory):
    suffix = Path(upload.original_filename or upload.media_file.name).suffix.lower() or ".media"
    with tempfile.NamedTemporaryFile(suffix=suffix, dir=directory, delete=False) as temporary_file:
        temporary_path = Path(temporary_file.name)
        try:
            upload.media_file.open("rb")
            for chunk in upload.media_file.chunks():
                temporary_file.write(chunk)
        finally:
            upload.media_file.close()
    return temporary_path


def _run_ffmpeg(command):
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        details = "\n".join(part for part in [result.stdout, result.stderr] if part)
        raise RuntimeError(details or f"FFmpeg a echoue avec le code {result.returncode}")


def _apply_soundtrack_if_available(input_path, output_path, soundtrack, ffmpeg_binary):
    if not soundtrack.track_path:
        return input_path
    if not _media_file_has_audio(input_path):
        return input_path

    _run_ffmpeg(
        [
            ffmpeg_binary,
            "-y",
            "-i",
            str(input_path),
            "-stream_loop",
            "-1",
            "-i",
            str(soundtrack.track_path),
            "-filter_complex",
            (
                f"[0:a]aresample=48000,volume={settings.MEMORA_MOVIE_VOICE_VOLUME}[voice];"
                f"[1:a]aresample=48000,volume={settings.MEMORA_MOVIE_MUSIC_VOLUME}[music];"
                "[music][voice]sidechaincompress=threshold=0.035:ratio=10:attack=80:release=900[ducked];"
                "[voice][ducked]amix=inputs=2:duration=first:dropout_transition=2[a]"
            ),
            "-map",
            "0:v:0",
            "-map",
            "[a]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-shortest",
            str(output_path),
        ]
    )
    return output_path


def _apply_event_badge(input_path, output_path, event, ffmpeg_binary, work_dir):
    display_name = _event_display_name(event)
    if not settings.MEMORA_MOVIE_BADGE_ENABLED or not display_name:
        return input_path

    brand_file = work_dir / "badge_brand.txt"
    title_file = work_dir / "badge_title.txt"
    brand_file.write_text("MEMORA", encoding="utf-8")
    title_file.write_text(_shorten_badge_text(display_name), encoding="utf-8")

    brand_path = _escape_filter_path(brand_file)
    title_path = _escape_filter_path(title_file)
    video_filter = (
        "drawbox=x=44:y=ih-126:w=640:h=80:color=0x241F22@0.58:t=fill,"
        "drawbox=x=44:y=ih-126:w=5:h=80:color=0xA45D6A@0.96:t=fill,"
        f"drawtext=font='Arial':textfile='{brand_path}':x=78:y=h-110:fontcolor=0xF5EAE4:fontsize=17,"
        f"drawtext=font='Arial':textfile='{title_path}':x=78:y=h-86:fontcolor=white:fontsize=34"
    )

    _run_ffmpeg(
        [
            ffmpeg_binary,
            "-y",
            "-i",
            str(input_path),
            "-vf",
            video_filter,
            "-map",
            "0:v:0",
            "-map",
            "0:a?",
            "-c:v",
            settings.MEMORA_MOVIE_VIDEO_ENCODER,
            "-c:a",
            "copy",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    )
    return output_path


def _event_display_name(event):
    return (event.couple_name or event.title or "").strip()


def _shorten_badge_text(value, max_length=38):
    normalized = " ".join((value or "").split())
    if len(normalized) <= max_length:
        return normalized
    return f"{normalized[: max_length - 3].rstrip()}..."


def _escape_filter_path(path):
    return path.as_posix().replace(":", "\\:").replace("'", "\\'")


def _media_file_has_audio(path):
    ffprobe_binary = settings.MEMORA_FFPROBE_BINARY
    if shutil.which(ffprobe_binary) is None and not Path(ffprobe_binary).exists():
        return False

    result = subprocess.run(
        [
            ffprobe_binary,
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "csv=p=0",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0 and "audio" in result.stdout.lower()


def _category_folder_name(category):
    default_name = DEFAULT_ZIP_CATEGORY_FOLDERS.get(category.code)
    if default_name:
        return default_name
    return f"{category.sort_order:02d}_{_clean_name(category.label)}"


def _build_archive_name(upload):
    uploaded_at = timezone.localtime(upload.uploaded_at)
    timestamp = uploaded_at.strftime("%Y-%m-%d_%H-%M-%S")
    extension = Path(upload.original_filename).suffix.lower()
    if not extension:
        extension = Path(upload.media_file.name).suffix.lower()
    return f"{timestamp}_{upload.media_type}{extension}"


def _dedupe_path(path, used_paths):
    if path not in used_paths:
        used_paths.add(path)
        return path

    stem = Path(path).stem
    suffix = Path(path).suffix
    parent = str(Path(path).parent).replace("\\", "/")
    counter = 2
    while True:
        candidate = f"{parent}/{stem}_{counter}{suffix}"
        if candidate not in used_paths:
            used_paths.add(candidate)
            return candidate
        counter += 1
