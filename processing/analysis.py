from pathlib import Path
import subprocess
import tempfile

from django.conf import settings
from django.utils import timezone
from PIL import Image, ImageFilter, ImageStat

from uploads.models import GuestUpload

from .google_video import GOOGLE_PROVIDER, analyze_video_with_google
from .models import MediaAnalysis


EMOTION_CATEGORY_BOOSTS = {
    "ceremony": 18,
    "speech": 16,
    "dancefloor": 12,
    "cake": 14,
    "funny": 18,
    "emotional": 24,
}

ENERGY_CATEGORY_BOOSTS = {
    "arrival": 10,
    "cocktail": 8,
    "reception": 8,
    "dancefloor": 24,
    "cake": 12,
    "funny": 16,
}


def create_media_analysis_job(upload):
    analysis, _created = MediaAnalysis.objects.get_or_create(upload=upload)
    return analysis


def get_uploads_needing_analysis(limit=None):
    queryset = GuestUpload.objects.filter(
        is_deleted=False,
        moderation_status=GuestUpload.ModerationStatus.APPROVED,
        analysis__isnull=True,
    ).order_by("uploaded_at", "pk")
    if limit:
        return list(queryset[:limit])
    return list(queryset)


def create_missing_media_analysis_jobs(limit=None):
    return [create_media_analysis_job(upload) for upload in get_uploads_needing_analysis(limit=limit)]


def get_pending_media_analyses(limit=None):
    queryset = (
        MediaAnalysis.objects.filter(status=MediaAnalysis.Status.PENDING)
        .select_related("upload", "upload__category", "upload__event")
        .order_by("created_at", "pk")
    )
    if limit:
        return list(queryset[:limit])
    return list(queryset)


def analyze_pending_media(limit=None):
    create_missing_media_analysis_jobs(limit=limit)
    processed_analyses = []
    for analysis in get_pending_media_analyses(limit=limit):
        processed_analyses.append(process_media_analysis(analysis))
    return processed_analyses


def analyze_event_media(event):
    uploads = GuestUpload.objects.filter(
        event=event,
        is_deleted=False,
        moderation_status=GuestUpload.ModerationStatus.APPROVED,
    ).select_related("category", "event")

    for upload in uploads.filter(analysis__isnull=True):
        create_media_analysis_job(upload)

    analyses = (
        MediaAnalysis.objects.filter(
            upload__event=event,
            status=MediaAnalysis.Status.PENDING,
        )
        .select_related("upload", "upload__category", "upload__event")
        .order_by("created_at", "pk")
    )

    return [process_media_analysis(analysis) for analysis in analyses]


def process_media_analysis(analysis):
    analysis.refresh_from_db()
    if analysis.status not in {MediaAnalysis.Status.PENDING, MediaAnalysis.Status.PROCESSING}:
        return analysis

    upload = analysis.upload
    analysis.status = MediaAnalysis.Status.PROCESSING
    analysis.error_logs = ""
    analysis.save(update_fields=["status", "error_logs", "updated_at"])

    try:
        provider_payload = {}
        with tempfile.TemporaryDirectory(prefix="memora_analysis_") as temp_dir:
            temp_path = Path(temp_dir)
            if upload.media_type == GuestUpload.MediaType.VIDEO:
                source_path = _copy_media_to_temporary_file(upload, temp_path)
                frame_path = temp_path / "frame.jpg"
                _extract_video_frame(source_path, frame_path)
                metrics = _analyze_image(frame_path)
                if _should_use_google_video_intelligence(upload):
                    provider_payload = analyze_video_with_google(source_path)
            else:
                source_path = _copy_media_to_temporary_file(upload, temp_path)
                metrics = _analyze_image(source_path)

        scores = _score_upload(upload, metrics, provider_payload=provider_payload)
        analysis.status = MediaAnalysis.Status.COMPLETED
        analysis.provider = provider_payload.get("provider", "local_heuristic_v1")
        analysis.technical_score = scores["technical_score"]
        analysis.emotion_score = scores["emotion_score"]
        analysis.energy_score = scores["energy_score"]
        analysis.movie_score = scores["movie_score"]
        analysis.brightness = metrics["brightness"]
        analysis.sharpness = metrics["sharpness"]
        analysis.tags = scores["tags"]
        analysis.provider_payload = provider_payload
        analysis.summary = scores["summary"]
        analysis.analyzed_at = timezone.now()
        analysis.error_logs = ""
        analysis.save(
            update_fields=[
                "status",
                "provider",
                "technical_score",
                "emotion_score",
                "energy_score",
                "movie_score",
                "brightness",
                "sharpness",
                "tags",
                "provider_payload",
                "summary",
                "analyzed_at",
                "error_logs",
                "updated_at",
            ]
        )
    except Exception as exc:
        analysis.status = MediaAnalysis.Status.FAILED
        analysis.error_logs = str(exc)
        analysis.save(update_fields=["status", "error_logs", "updated_at"])

    return analysis


def _should_use_google_video_intelligence(upload):
    return (
        settings.MEMORA_GOOGLE_VIDEO_INTELLIGENCE_ENABLED
        and settings.MEMORA_AI_ANALYSIS_PROVIDER == GOOGLE_PROVIDER
        and upload.media_type == GuestUpload.MediaType.VIDEO
    )


def _analyze_image(path):
    with Image.open(path) as image:
        grayscale = image.convert("L")
        stat = ImageStat.Stat(grayscale)
        brightness = _clamp(stat.mean[0] / 255 * 100)
        contrast = _clamp(stat.stddev[0] / 90 * 100)
        edges = grayscale.filter(ImageFilter.FIND_EDGES)
        sharpness = _clamp(ImageStat.Stat(edges).mean[0] / 36 * 100)

    return {
        "brightness": brightness,
        "contrast": contrast,
        "sharpness": sharpness,
    }


def _score_upload(upload, metrics, provider_payload=None):
    provider_payload = provider_payload or {}
    brightness_score = _clamp(100 - abs(metrics["brightness"] - 55) * 2.2)
    technical_score = _clamp(
        brightness_score * 0.45
        + metrics["sharpness"] * 0.35
        + metrics["contrast"] * 0.20
    )

    category_code = upload.category.code
    emotion_score = 45 + EMOTION_CATEGORY_BOOSTS.get(category_code, 8)
    energy_score = 50 + ENERGY_CATEGORY_BOOSTS.get(category_code, 6)

    if upload.media_type == GuestUpload.MediaType.VIDEO:
        emotion_score += 8
        energy_score += 14
        if upload.duration:
            seconds = upload.duration.total_seconds()
            if 4 <= seconds <= settings.MEMORA_MAX_VIDEO_UPLOAD_DURATION_SECONDS:
                emotion_score += 6
                energy_score += 4
            elif seconds < 2:
                energy_score -= 12
    else:
        emotion_score -= 4
        energy_score -= 10

    provider_scores = _score_provider_payload(provider_payload)
    emotion_score += provider_scores["emotion_boost"]
    energy_score += provider_scores["energy_boost"]
    technical_score -= provider_scores["technical_penalty"]

    tags = _build_tags(upload, metrics) + provider_scores["tags"]
    movie_score = _clamp(
        technical_score * 0.42
        + _clamp(emotion_score) * 0.34
        + _clamp(energy_score) * 0.24
    )

    return {
        "technical_score": round(technical_score, 2),
        "emotion_score": round(_clamp(emotion_score), 2),
        "energy_score": round(_clamp(energy_score), 2),
        "movie_score": round(movie_score, 2),
        "tags": list(dict.fromkeys(tags)),
        "summary": _build_summary(upload, movie_score, tags),
    }


def _score_provider_payload(payload):
    labels = {
        label["description"].lower()
        for label in payload.get("labels", [])
        if label.get("description")
    }
    speech_segments = payload.get("speech_segments", [])
    face_track_count = payload.get("face_track_count", 0) or 0
    shot_count = payload.get("shot_count", 0) or 0
    explicit_likelihood = payload.get("explicit_content", {}).get("max_likelihood", 0) or 0

    emotion_boost = min(face_track_count * 3, 15)
    energy_boost = min(max(shot_count - 1, 0) * 2, 12)
    technical_penalty = 0
    tags = []

    if face_track_count:
        tags.append("visages")
    if speech_segments:
        emotion_boost += 12
        tags.append("voix")
    if labels & {"wedding", "bride", "groom", "dance", "dancing", "party", "speech", "laughter"}:
        emotion_boost += 10
        tags.append("moment_humain")
    if labels & {"dance", "dancing", "party", "concert", "performance"}:
        energy_boost += 10
        tags.append("energie")
    if explicit_likelihood >= 4:
        technical_penalty += 55
        tags.append("contenu_sensible")
    elif explicit_likelihood == 3:
        technical_penalty += 24
        tags.append("contenu_a_verifier")

    return {
        "emotion_boost": emotion_boost,
        "energy_boost": energy_boost,
        "technical_penalty": technical_penalty,
        "tags": tags,
    }


def _build_tags(upload, metrics):
    tags = [upload.media_type, upload.category.code]
    if metrics["brightness"] < 28:
        tags.append("sombre")
    elif metrics["brightness"] > 78:
        tags.append("lumineux")
    else:
        tags.append("exposition_ok")

    if metrics["sharpness"] < 28:
        tags.append("peu_net")
    elif metrics["sharpness"] > 62:
        tags.append("net")

    if upload.category.code in {"funny", "emotional", "dancefloor", "ceremony", "speech"}:
        tags.append("moment_fort")

    return tags


def _build_summary(upload, movie_score, tags):
    if movie_score >= 75:
        prefix = "Excellent candidat"
    elif movie_score >= 58:
        prefix = "Bon candidat"
    else:
        prefix = "Candidat secondaire"
    return f"{prefix} pour le film: {upload.category.label.lower()} ({', '.join(tags[:4])})."


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


def _extract_video_frame(source_path, frame_path):
    command = [
        settings.MEMORA_FFMPEG_BINARY,
        "-y",
        "-ss",
        "00:00:01",
        "-i",
        str(source_path),
        "-frames:v",
        "1",
        str(frame_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        details = "\n".join(part for part in [result.stdout, result.stderr] if part)
        raise RuntimeError(details or f"FFmpeg a echoue avec le code {result.returncode}")
    if not frame_path.exists():
        raise RuntimeError("Aucune frame video extraite pour l'analyse.")


def _clamp(value, minimum=0, maximum=100):
    return max(minimum, min(maximum, float(value)))
