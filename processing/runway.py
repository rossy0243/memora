from pathlib import Path
from time import sleep

import httpx
from django.conf import settings


RUNWAY_PROVIDER = "runway"
RUNWAY_FINAL_PROVIDER = "runway_final"
RUNWAY_DIRECT_MODE = "direct_video_to_video"
RUNWAY_FINAL_MODE = "published_workflow_final_movie"
RUNWAY_API_BASE_URL = "https://api.dev.runwayml.com"


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


def build_runway_final_payload(event, uploads, edit_decision_data):
    return {
        "mode": RUNWAY_FINAL_MODE,
        "brief": _final_movie_brief(event, edit_decision_data),
        "constraints": {
            "max_duration_seconds": settings.MEMORA_MOVIE_MAX_DURATION_SECONDS,
            "target_ratio": settings.MEMORA_RUNWAY_VIDEO_RATIO,
            "style": "premium cinematic event memory film",
            "include_photos": True,
            "preserve_people_and_real_moments": True,
            "avoid_fictional_content": True,
            "music_ducking": edit_decision_data.get("audio_strategy", {}),
            "badge_text": _event_display_name(event),
        },
        "event": {
            "id": event.pk,
            "title": event.title,
            "display_name": _event_display_name(event),
            "type": getattr(event.event_type, "code", ""),
            "date": event.event_date.isoformat(),
            "location": event.location,
        },
        "soundtrack": edit_decision_data.get("soundtrack", {}),
        "media": [_media_payload(upload) for upload in uploads],
    }


def runway_is_ready():
    return (
        settings.MEMORA_RUNWAY_ENABLED
        and settings.MEMORA_MOVIE_RENDER_PROVIDER in {RUNWAY_PROVIDER, RUNWAY_FINAL_PROVIDER}
        and bool(settings.MEMORA_RUNWAY_API_SECRET)
    )


def runway_final_is_ready():
    return (
        settings.MEMORA_RUNWAY_ENABLED
        and settings.MEMORA_MOVIE_RENDER_PROVIDER == RUNWAY_FINAL_PROVIDER
        and bool(settings.MEMORA_RUNWAY_API_SECRET)
        and bool(settings.MEMORA_RUNWAY_WORKFLOW_ID)
    )


def render_final_movie_with_runway(event, uploads, edit_decision_data, output_path):
    payload = build_runway_final_payload(event, uploads, edit_decision_data)
    invocation = _run_workflow(payload)
    output_url = _find_output_url(invocation)
    if not output_url:
        raise RuntimeError("Runway n'a retourne aucune URL de film final.")

    _download_runway_output(output_url, output_path)
    return {
        "workflow_id": settings.MEMORA_RUNWAY_WORKFLOW_ID,
        "invocation_id": _invocation_id(invocation),
        "mode": RUNWAY_FINAL_MODE,
        "output_file": Path(output_path).name,
        "output_url_received": True,
        "payload_summary": {
            "media_count": len(payload["media"]),
            "event_title": payload["event"]["title"],
            "display_name": payload["event"]["display_name"],
            "max_duration_seconds": payload["constraints"]["max_duration_seconds"],
            "style": payload["constraints"]["style"],
        },
    }


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


def _run_workflow(payload):
    headers = {
        "Authorization": f"Bearer {settings.MEMORA_RUNWAY_API_SECRET}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-Runway-Version": settings.MEMORA_RUNWAY_WORKFLOW_VERSION,
    }
    workflow_url = f"{RUNWAY_API_BASE_URL}/v1/workflows/{settings.MEMORA_RUNWAY_WORKFLOW_ID}"
    request_payload = {"inputs": payload}
    with httpx.Client(timeout=60) as client:
        response = client.post(workflow_url, headers=headers, json=request_payload)
        response.raise_for_status()
        invocation = response.json()
        invocation_id = _invocation_id(invocation)
        if not invocation_id:
            return invocation

        return _poll_workflow_invocation(client, headers, invocation_id)


def _poll_workflow_invocation(client, headers, invocation_id):
    deadline_seconds = max(settings.MEMORA_RUNWAY_TASK_TIMEOUT_SECONDS, 30)
    attempts = max(deadline_seconds // 5, 1)
    detail_url = f"{RUNWAY_API_BASE_URL}/v1/workflows/invocations/{invocation_id}"
    latest = {}
    for _attempt in range(attempts):
        response = client.get(detail_url, headers=headers)
        response.raise_for_status()
        latest = response.json()
        status = _status_value(latest)
        if status in {"succeeded", "success", "completed", "complete", "finished"}:
            return latest
        if status in {"failed", "error", "canceled", "cancelled"}:
            raise RuntimeError(f"Runway workflow failed: {latest}")
        sleep(5)

    raise TimeoutError(f"Runway workflow timeout after {deadline_seconds} seconds: {latest}")


def _invocation_id(value):
    if not isinstance(value, dict):
        return ""
    for key in ("id", "invocation_id", "invocationId", "task_id", "taskId"):
        if value.get(key):
            return value[key]
    nested = value.get("workflowInvocation") or value.get("invocation") or value.get("task")
    if isinstance(nested, dict):
        return _invocation_id(nested)
    return ""


def _status_value(value):
    if not isinstance(value, dict):
        return ""
    status = value.get("status") or value.get("state")
    if status:
        return str(status).lower()
    nested = value.get("workflowInvocation") or value.get("invocation") or value.get("task")
    if isinstance(nested, dict):
        return _status_value(nested)
    return ""


def _find_output_url(value):
    if isinstance(value, str):
        if value.startswith("http://") or value.startswith("https://"):
            return value
        return ""
    if isinstance(value, dict):
        for key in ("video", "video_url", "videoUrl", "url", "uri", "output_url", "outputUrl"):
            output_url = _find_output_url(value.get(key))
            if output_url:
                return output_url
        for key in ("output", "outputs", "result", "results", "data", "workflowInvocation", "invocation", "task"):
            output_url = _find_output_url(value.get(key))
            if output_url:
                return output_url
    if isinstance(value, list):
        for item in value:
            output_url = _find_output_url(item)
            if output_url:
                return output_url
    return ""


def _style_prompt(event, edit_decision_data):
    mood = edit_decision_data.get("soundtrack", {}).get("mood", "elegant_warm")
    return (
        settings.MEMORA_RUNWAY_PROMPT[:880]
        + f" Event: {event.title}. Music mood: {mood}."
    )


def _final_movie_brief(event, edit_decision_data):
    display_name = _event_display_name(event) or event.title
    soundtrack = edit_decision_data.get("soundtrack", {})
    return (
        f"Create the final Memora souvenir film for {display_name}. "
        "Use the selected guest photos and videos as authentic source material. "
        "The result must feel like a premium cinematic event memory film: emotional, elegant, warm, "
        "natural skin tones, tasteful transitions, and a clear narrative arc from arrival to celebration. "
        "Keep real voices when they carry emotion, lower background music under speech, and restore music between voices. "
        f"Target mood: {soundtrack.get('mood', 'elegant_warm')}. "
        "Do not invent people or events. Do not remove important photos."
    )


def _media_payload(upload):
    try:
        media_url = upload.media_file.url
    except Exception:
        media_url = ""
    return {
        "upload_id": upload.pk,
        "url": media_url,
        "filename": upload.original_filename,
        "media_type": upload.media_type,
        "category": upload.category.code,
        "category_label": upload.category.label,
        "score": _analysis_score(upload),
        "duration": _duration(upload),
        "selected_for_movie": upload.is_selected_for_movie,
    }


def _event_display_name(event):
    return (event.couple_name or event.title or "").strip()


def _analysis_score(upload):
    try:
        return round(upload.analysis.movie_score, 2)
    except Exception:
        return None


def _duration(upload):
    if upload.duration:
        return round(upload.duration.total_seconds(), 3)
    return None
