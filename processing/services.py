from datetime import datetime, time, timedelta
from io import BytesIO
from pathlib import Path
import shutil
import subprocess
import tempfile
from zipfile import ZIP_DEFLATED, ZipFile

from django.conf import settings
from django.core.files.base import File
from django.utils import timezone
from django.utils.text import slugify

from uploads.models import GuestUpload

from .analysis import analyze_event_media
from .models import GeneratedMovie, MediaAnalysis


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

    videos = [upload for upload in uploads if upload.media_type == GuestUpload.MediaType.VIDEO]
    candidate_pool = videos or uploads
    candidate_pool.sort(
        key=lambda upload: (
            score_movie_candidate(upload),
            upload.uploaded_at,
            upload.pk,
        ),
        reverse=True,
    )

    selected_uploads = []
    total_duration = 0
    max_duration = settings.MEMORA_MOVIE_MAX_DURATION_SECONDS

    for upload in candidate_pool:
        estimated_duration = _estimated_movie_clip_duration(upload)
        if total_duration + estimated_duration > max_duration:
            continue
        selected_uploads.append(upload)
        total_duration += estimated_duration
        if total_duration >= max_duration:
            break

    return selected_uploads


def score_movie_candidate(upload):
    try:
        analysis = upload.analysis
    except MediaAnalysis.DoesNotExist:
        analysis = None

    if analysis and analysis.status == MediaAnalysis.Status.COMPLETED:
        score = analysis.movie_score
        if upload.media_type == GuestUpload.MediaType.VIDEO:
            score += 18
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


def get_event_movie_schedule_at(event):
    scheduled_date = event.event_date + timedelta(days=1)
    scheduled_time = time(hour=settings.MEMORA_MOVIE_AUTOGENERATE_HOUR)
    scheduled_at = datetime.combine(scheduled_date, scheduled_time)
    return timezone.make_aware(scheduled_at, timezone.get_current_timezone())


def get_scheduled_movie_events(now=None):
    from events.models import Event

    now = timezone.localtime(now or timezone.now())
    events = Event.objects.filter(is_active=True).order_by("event_date", "pk")

    scheduled_events = []
    for event in events:
        if get_event_movie_schedule_at(event) > now:
            continue

        has_existing_movie = event.generated_movies.filter(
            status__in=[
                GeneratedMovie.Status.PENDING,
                GeneratedMovie.Status.PROCESSING,
                GeneratedMovie.Status.COMPLETED,
            ]
        ).exists()
        if has_existing_movie:
            continue

        if not get_movie_candidate_uploads(event):
            continue

        scheduled_events.append(event)

    return scheduled_events


def create_event_movie_job(event):
    existing_job = (
        event.generated_movies.filter(
            status__in=[
                GeneratedMovie.Status.PENDING,
                GeneratedMovie.Status.PROCESSING,
            ]
        )
        .order_by("-created_at")
        .first()
    )
    if existing_job:
        return existing_job
    return GeneratedMovie.objects.create(event=event, status=GeneratedMovie.Status.PENDING)


def get_pending_movie_jobs(limit=None):
    queryset = (
        GeneratedMovie.objects.filter(status=GeneratedMovie.Status.PENDING)
        .select_related("event")
        .order_by("created_at", "pk")
    )
    if limit:
        return list(queryset[:limit])
    return list(queryset)


def process_pending_movie_jobs(limit=None):
    processed_movies = []
    for movie in get_pending_movie_jobs(limit=limit):
        processed_movies.append(process_generated_movie(movie))
    return processed_movies


def generate_event_movie(event):
    movie = create_event_movie_job(event)
    return process_generated_movie(movie)


def process_generated_movie(movie):
    movie.refresh_from_db()
    if movie.status not in {GeneratedMovie.Status.PENDING, GeneratedMovie.Status.PROCESSING}:
        return movie

    event = movie.event
    analyze_event_media(event)
    uploads = list(get_movie_candidate_uploads(event))

    if not uploads:
        movie.status = GeneratedMovie.Status.FAILED
        movie.error_logs = "Aucun media accepte disponible pour generer le film souvenir."
        movie.save(update_fields=["status", "error_logs", "updated_at"])
        return movie

    ffmpeg_binary = settings.MEMORA_FFMPEG_BINARY
    if shutil.which(ffmpeg_binary) is None and not Path(ffmpeg_binary).exists():
        movie.status = GeneratedMovie.Status.FAILED
        movie.error_logs = f"FFmpeg introuvable: {ffmpeg_binary}"
        movie.save(update_fields=["status", "error_logs", "updated_at"])
        return movie

    movie.status = GeneratedMovie.Status.PROCESSING
    movie.save(update_fields=["status", "updated_at"])

    try:
        with tempfile.TemporaryDirectory(prefix="memora_movie_") as temp_dir:
            temp_path = Path(temp_dir)
            clip_paths = []
            total_duration = 0
            for index, upload in enumerate(uploads, start=1):
                clip_path = temp_path / f"clip_{index:04d}.mp4"
                _build_movie_clip(upload, clip_path, ffmpeg_binary)
                clip_paths.append(clip_path)
                total_duration += _estimated_movie_clip_duration(upload)

            concat_file = temp_path / "clips.txt"
            concat_file.write_text(
                "".join(f"file '{path.as_posix()}'\n" for path in clip_paths),
                encoding="utf-8",
            )
            output_path = temp_path / f"memora_{_clean_name(event.title)}.mp4"
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
                    str(output_path),
                ]
            )

            with output_path.open("rb") as output_file:
                movie.final_file.save(output_path.name, File(output_file), save=False)

        movie.status = GeneratedMovie.Status.COMPLETED
        movie.generated_at = timezone.now()
        movie.duration = timedelta(seconds=min(total_duration, settings.MEMORA_MOVIE_MAX_DURATION_SECONDS))
        movie.error_logs = ""
        movie.save(
            update_fields=[
                "final_file",
                "status",
                "generated_at",
                "duration",
                "error_logs",
                "updated_at",
            ]
        )
    except Exception as exc:
        movie.status = GeneratedMovie.Status.FAILED
        movie.error_logs = str(exc)
        movie.save(update_fields=["status", "error_logs", "updated_at"])

    return movie


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
            command = [
                ffmpeg_binary,
                "-y",
                "-loop",
                "1",
                "-t",
                str(settings.MEMORA_MOVIE_IMAGE_DURATION_SECONDS),
                "-i",
                str(input_path),
                "-vf",
                video_filter,
                "-an",
                "-c:v",
                settings.MEMORA_MOVIE_VIDEO_ENCODER,
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
                "-t",
                str(settings.MEMORA_MOVIE_VIDEO_MAX_SECONDS),
                "-vf",
                video_filter,
                "-an",
                "-c:v",
                settings.MEMORA_MOVIE_VIDEO_ENCODER,
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
