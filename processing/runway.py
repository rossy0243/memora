from django.conf import settings


RUNWAY_PROVIDER = "runway"


def build_runway_montage_payload(event, uploads, edit_decision_data):
    return {
        "workflow_id": settings.MEMORA_RUNWAY_WORKFLOW_ID,
        "workflow_version": settings.MEMORA_RUNWAY_WORKFLOW_VERSION,
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
        and bool(settings.MEMORA_RUNWAY_WORKFLOW_ID)
    )


def _style_prompt(event, edit_decision_data):
    mood = edit_decision_data.get("soundtrack", {}).get("mood", "elegant_warm")
    return (
        "Create a premium, emotional event memory film. "
        "Keep the guests' authentic voices when they matter, lower background music under speech, "
        "bring music back between spoken moments, use elegant pacing, clean transitions, "
        f"and keep the final movie under {settings.MEMORA_MOVIE_MAX_DURATION_SECONDS} seconds. "
        f"Event: {event.title}. Music mood: {mood}."
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
