from django.conf import settings


RUNWAY_PROVIDER = "runway"
RUNWAY_DIRECT_MODE = "direct_video_to_video"


def build_runway_montage_payload(event, uploads, edit_decision_data):
    return {
        "mode": RUNWAY_DIRECT_MODE,
        "workflow_id": settings.MEMORA_RUNWAY_WORKFLOW_ID,
        "workflow_version": settings.MEMORA_RUNWAY_WORKFLOW_VERSION,
        "model": settings.MEMORA_RUNWAY_VIDEO_MODEL,
        "ratio": settings.MEMORA_RUNWAY_VIDEO_RATIO,
        "max_enhanced_clips": settings.MEMORA_RUNWAY_MAX_ENHANCED_CLIPS,
        "style_prompt": _style_prompt(event, edit_decision_data),
        "event": {
            "id": event.pk,
            "title": event.title,
            "type": getattr(event.event_type, "code", ""),
            "date": event.event_date.isoformat(),
            "location": event.location,
        },
        "soundtrack": edit_decision_data.get("soundtrack", {}),
        "audio_strategy": edit_decision_data.get("audio_strategy", {}),
        "clips": [
            {
                "upload_id": upload.pk,
                "filename": upload.original_filename,
                "category": upload.category.code,
                "score": _analysis_score(upload),
                "duration": _duration(upload),
            }
            for upload in uploads
        ],
    }


def runway_is_ready():
    return (
        settings.MEMORA_RUNWAY_ENABLED
        and settings.MEMORA_MOVIE_RENDER_PROVIDER == RUNWAY_PROVIDER
        and bool(settings.MEMORA_RUNWAY_API_SECRET)
    )


def enhance_clip_with_runway(input_path, output_path, prompt_text=None):
    try:
        from runwayml import RunwayML
    except ImportError as exc:
        raise RuntimeError(
            "runwayml n'est pas installe. Installe les dependances avec pip install -r requirements.txt."
        ) from exc

    client = RunwayML(api_key=settings.MEMORA_RUNWAY_API_SECRET)
    with open(input_path, "rb") as input_file:
        upload = client.uploads.create_ephemeral(file=(input_path.name, input_file))

    task = client.video_to_video.create(
        model=settings.MEMORA_RUNWAY_VIDEO_MODEL,
        video_uri=upload.uri,
        prompt_text=prompt_text or settings.MEMORA_RUNWAY_PROMPT,
        ratio=settings.MEMORA_RUNWAY_VIDEO_RATIO,
    )
    completed_task = task.wait_for_task_output(timeout=settings.MEMORA_RUNWAY_TASK_TIMEOUT_SECONDS)

    if not completed_task.output:
        raise RuntimeError(f"Runway n'a retourne aucune video pour la tache {completed_task.id}.")

    _download_runway_output(completed_task.output[0], output_path)
    return {
        "task_id": completed_task.id,
        "output_count": len(completed_task.output),
        "output_file": output_path.name,
    }


def _download_runway_output(output_url, output_path):
    import shutil
    from urllib.request import urlopen

    with urlopen(output_url, timeout=120) as response:
        with open(output_path, "wb") as output_file:
            shutil.copyfileobj(response, output_file)


def _style_prompt(event, edit_decision_data):
    mood = edit_decision_data.get("soundtrack", {}).get("mood", "elegant_warm")
    return (
        settings.MEMORA_RUNWAY_PROMPT[:880]
        + f" Event: {event.title}. Music mood: {mood}."
    )


def _analysis_score(upload):
    try:
        return round(upload.analysis.movie_score, 2)
    except Exception:
        return None


def _duration(upload):
    if upload.duration:
        return round(upload.duration.total_seconds(), 3)
    return None
