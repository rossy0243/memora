"""Montage integral du livre d'or via Remotion.

Livrable distinct du film souvenir : tous les messages video des invites, en
entier, dans l'ordre chronologique, chacun precede d'un carton « De la part
de … ». Meme moteur premium que le film (composition Remotion `GuestBook`),
mais la musique n'est qu'un lit discret, encore baisse pendant chaque message.
"""
import json
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.utils import timezone

from .remotion import _materialize_upload, _normalize_clip_audio
from .soundtrack import choose_movie_soundtrack, materialize_soundtrack

logger = logging.getLogger(__name__)

_GRADE_BY_MOOD = {
    "romantic_cinematic": "romantic",
    "warm_lounge": "warm",
    "cinematic_emotional": "romantic",
    "elegant_warm": "warm",
    "joyful_party": "neutral",
}


def _seconds_to_frames(seconds, fps):
    return max(int(round(seconds * fps)), 1)


def _message_seconds(message):
    """Duree reelle du message. Le livre d'or est integral : on ne coupe pas."""
    ceiling = settings.MEMORA_GUESTBOOK_MAX_VIDEO_DURATION_SECONDS * 2
    if message.duration:
        return max(min(message.duration.total_seconds(), ceiling), 1.0)
    return float(settings.MEMORA_GUESTBOOK_MAX_VIDEO_DURATION_SECONDS)


def build_guestbook_props(event, messages, soundtrack, *, fps=None):
    """Construit le dict `GuestBookProps` (aligne sur remotion/src/types.ts)."""
    fps = fps or settings.MEMORA_REMOTION_FPS

    clips = []
    for index, message in enumerate(messages, start=1):
        suffix = Path(message.original_filename or message.media_file.name).suffix.lower() or ".mp4"
        clips.append(
            {
                "src": f"message_{index:04d}{suffix}",
                "durationInFrames": _seconds_to_frames(_message_seconds(message), fps),
                "guestName": (message.guest_name or "").strip(),
            }
        )

    audio_src = None
    audio_offset = 0.0
    if soundtrack and soundtrack.has_track:
        audio_ext = ".mp3"
        if soundtrack.track_path:
            audio_ext = Path(soundtrack.track_path).suffix or ".mp3"
        audio_src = f"music{audio_ext}"
        audio_offset = float(soundtrack.first_beat_offset or 0.0)

    return {
        "messages": clips,
        "audioSrc": audio_src,
        "audioFirstBeatOffset": audio_offset,
        "title": event.title,
        "subtitle": "Livre d'or",
        "outroTitle": settings.MEMORA_GUESTBOOK_MONTAGE_OUTRO_TITLE or "Merci",
        "introDurationInFrames": _seconds_to_frames(
            settings.MEMORA_GUESTBOOK_MONTAGE_INTRO_CARD_SECONDS, fps
        ),
        "outroDurationInFrames": _seconds_to_frames(
            settings.MEMORA_GUESTBOOK_MONTAGE_OUTRO_CARD_SECONDS, fps
        ),
        "nameCardDurationInFrames": _seconds_to_frames(
            settings.MEMORA_GUESTBOOK_MONTAGE_NAME_CARD_SECONDS, fps
        ),
        "transitionDurationInFrames": max(int(round(fps / 2)), 1),
        "grade": _GRADE_BY_MOOD.get(getattr(soundtrack, "mood", ""), "warm"),
        "musicVolume": float(settings.MEMORA_GUESTBOOK_MONTAGE_MUSIC_VOLUME),
        "duckedMusicVolume": float(settings.MEMORA_GUESTBOOK_MONTAGE_DUCKED_MUSIC_VOLUME),
    }


def render_guestbook_montage(event, messages, output_path):
    """Rend le montage du livre d'or via Remotion. Renvoie le chemin du MP4.

    Leve une exception si Node/Remotion echoue : l'appelant gere l'echec.
    """
    messages = list(messages)
    if not messages:
        raise ValueError("Aucun message de livre d'or a monter.")

    node_binary = shutil.which(settings.MEMORA_NODE_BINARY)
    if not node_binary:
        raise RuntimeError("Node introuvable : rendu Remotion impossible.")

    remotion_dir = Path(settings.MEMORA_REMOTION_DIR)
    render_script = remotion_dir / "render.mjs"
    if not render_script.exists():
        raise RuntimeError(f"Script de rendu absent : {render_script}")

    soundtrack = choose_movie_soundtrack(event, [])
    props = build_guestbook_props(event, messages, soundtrack)

    with tempfile.TemporaryDirectory(prefix="memora_guestbook_") as work_dir:
        assets_dir = Path(work_dir) / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)

        for clip, message in zip(props["messages"], messages):
            destination = assets_dir / clip["src"]
            _materialize_upload(message, destination)
            _normalize_clip_audio(destination, settings.MEMORA_FFMPEG_BINARY)

        if props["audioSrc"]:
            track_path, cleanup = materialize_soundtrack(soundtrack, assets_dir)
            if track_path:
                shutil.copy(track_path, assets_dir / props["audioSrc"])
                if cleanup:
                    Path(track_path).unlink(missing_ok=True)
            else:
                props["audioSrc"] = None

        props_path = Path(work_dir) / "props.json"
        props_path.write_text(json.dumps(props), encoding="utf-8")

        command = [
            node_binary,
            str(render_script),
            "--composition=GuestBook",
            f"--props={props_path}",
            f"--output={output_path}",
            f"--public-dir={assets_dir}",
        ]
        logger.info(
            "Guestbook montage render started event=%s messages=%s",
            event.pk,
            len(messages),
        )
        result = subprocess.run(
            command,
            cwd=str(remotion_dir),
            capture_output=True,
            text=True,
            timeout=settings.MEMORA_REMOTION_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Rendu Remotion du livre d'or echoue (code {result.returncode}) : "
                f"{(result.stderr or result.stdout or '').strip()[:500]}"
            )

    logger.info("Guestbook montage render completed event=%s", event.pk)
    return Path(output_path)


def process_guestbook_movie(movie):
    """Genere (ou regenere) le montage du livre d'or pour un `GuestBookMovie`."""
    from guestbook.models import GuestBookMovie

    movie.refresh_from_db()
    if movie.status not in {GuestBookMovie.Status.PENDING, GuestBookMovie.Status.PROCESSING}:
        logger.info("Guestbook montage skipped movie=%s status=%s", movie.pk, movie.status)
        return movie

    event = movie.event
    messages = list(event.guestbook_messages.order_by("created_at", "pk"))

    if not messages:
        movie.status = GuestBookMovie.Status.FAILED
        movie.error_message = "Aucun message dans le livre d'or."
        movie.save(update_fields=["status", "error_message", "updated_at"])
        return movie

    ffmpeg_binary = settings.MEMORA_FFMPEG_BINARY
    if shutil.which(ffmpeg_binary) is None and not Path(ffmpeg_binary).exists():
        movie.status = GuestBookMovie.Status.FAILED
        movie.error_message = f"FFmpeg introuvable : {ffmpeg_binary}"
        movie.save(update_fields=["status", "error_message", "updated_at"])
        return movie

    movie.status = GuestBookMovie.Status.PROCESSING
    movie.started_at = timezone.now()
    movie.error_message = ""
    movie.save(update_fields=["status", "started_at", "error_message", "updated_at"])

    try:
        with tempfile.TemporaryDirectory(prefix="memora_guestbook_out_") as out_dir:
            output_path = Path(out_dir) / f"livre-dor-{event.slug or event.pk}.mp4"
            render_guestbook_montage(event, messages, output_path)

            duration_seconds = sum(_message_seconds(message) for message in messages)
            with open(output_path, "rb") as rendered:
                movie.final_file.save(output_path.name, File(rendered), save=False)
    except Exception as exc:  # rendu Remotion / materialisation / storage
        logger.exception("Guestbook montage failed movie=%s event=%s", movie.pk, event.pk)
        movie.status = GuestBookMovie.Status.FAILED
        movie.error_message = str(exc)[:2000]
        movie.save(update_fields=["status", "error_message", "updated_at"])
        return movie

    movie.status = GuestBookMovie.Status.COMPLETED
    movie.render_provider = "remotion"
    movie.message_count = len(messages)
    movie.duration = timezone.timedelta(seconds=round(duration_seconds))
    movie.completed_at = timezone.now()
    movie.save(
        update_fields=[
            "status",
            "final_file",
            "render_provider",
            "message_count",
            "duration",
            "completed_at",
            "updated_at",
        ]
    )
    logger.info("Guestbook montage completed movie=%s event=%s messages=%s", movie.pk, event.pk, len(messages))
    return movie
