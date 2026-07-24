"""Integration Django -> Remotion : construit la liste de montage (EDL) et pilote le
rendu premium des films via le script Node `remotion/render.mjs`.

Remotion decrit la composition (React) ; ffmpeg reste le moteur d'encodage sous le
capot et le pipeline de secours. Ce module :
  1. construit un dict `FilmProps` aligne avec remotion/src/types.ts ;
  2. materialise les clips et la piste musicale (R2 -> dossier local) ;
  3. appelle `node render.mjs` en sous-processus et renvoie le MP4.
"""
import json
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from django.conf import settings

from uploads.models import GuestUpload

from .soundtrack import materialize_soundtrack
from .title_cards import event_intro_texts

logger = logging.getLogger(__name__)

# Formats (composition Remotion -> dimensions). Une seule composition parametree.
COMPOSITIONS = {
    "hero": {"id": "Hero", "width": 1920, "height": 1080},
    "full": {"id": "Full", "width": 1920, "height": 1080},
    "teaser": {"id": "Teaser", "width": 1080, "height": 1920},
}

# Mood de la piste -> accord colorimetrique de la composition.
_GRADE_BY_MOOD = {
    "romantic_cinematic": "romantic",
    "warm_lounge": "warm",
    "cinematic_emotional": "romantic",
    "elegant_warm": "warm",
    "joyful_party": "neutral",
}


def _seconds_to_frames(seconds, fps):
    return max(int(round(seconds * fps)), 1)


def _clip_seconds(upload, beat_interval):
    """Duree d'un plan, calee sur le tempo — meme logique que le pipeline ffmpeg."""
    from .services import snap_duration_to_beat

    if upload.media_type == GuestUpload.MediaType.IMAGE:
        base = settings.MEMORA_MOVIE_IMAGE_DURATION_SECONDS
        return snap_duration_to_beat(base, beat_interval)

    base = settings.MEMORA_MOVIE_VIDEO_MAX_SECONDS
    if upload.duration:
        base = min(upload.duration.total_seconds(), base)
    snapped = snap_duration_to_beat(base, beat_interval)
    # On ne rallonge jamais un plan au-dela de sa duree reelle (sinon image gelee).
    if snapped > base and beat_interval:
        snapped = max(snapped - beat_interval, beat_interval)
    return snapped


def build_film_props(event, uploads, soundtrack, *, fps=None):
    """Construit le dict FilmProps (aligne avec remotion/src/types.ts).

    Les `src` sont des noms de fichiers relatifs au dossier d'assets materialise ;
    la piste musicale est nommee `music.<ext>`.
    """
    fps = fps or settings.MEMORA_REMOTION_FPS
    beat_interval = soundtrack.beat_interval if soundtrack else 0.0

    clips = []
    for index, upload in enumerate(uploads, start=1):
        suffix = Path(upload.original_filename or upload.media_file.name).suffix.lower() or ".media"
        seconds = _clip_seconds(upload, beat_interval)
        clips.append(
            {
                "kind": "video" if upload.media_type == GuestUpload.MediaType.VIDEO else "image",
                "src": f"clip_{index:04d}{suffix}",
                "durationInFrames": _seconds_to_frames(seconds, fps),
                "category": getattr(getattr(upload, "category", None), "code", "") or "",
            }
        )

    title, subtitle = event_intro_texts(event)

    audio_src = None
    audio_offset = 0.0
    if soundtrack and soundtrack.has_track:
        audio_ext = ".mp3"
        if soundtrack.track_path:
            audio_ext = Path(soundtrack.track_path).suffix or ".mp3"
        audio_src = f"music{audio_ext}"
        audio_offset = float(soundtrack.first_beat_offset or 0.0)

    return {
        "clips": clips,
        "audioSrc": audio_src,
        "audioFirstBeatOffset": audio_offset,
        "title": title or event.title,
        "subtitle": subtitle,
        "outroTitle": settings.MEMORA_MOVIE_OUTRO_TITLE or "Merci",
        "introDurationInFrames": _seconds_to_frames(settings.MEMORA_MOVIE_INTRO_CARD_SECONDS, fps),
        "outroDurationInFrames": _seconds_to_frames(settings.MEMORA_MOVIE_OUTRO_CARD_SECONDS, fps),
        "transitionDurationInFrames": max(int(round(fps / 2)), 1),
        "grade": _GRADE_BY_MOOD.get(getattr(soundtrack, "mood", ""), "romantic"),
    }


def _materialize_upload(upload, destination):
    """Copie le media (R2 ou local) vers `destination` via l'API de stockage."""
    upload.media_file.open("rb")
    try:
        with open(destination, "wb") as target:
            for chunk in upload.media_file.chunks():
                target.write(chunk)
    finally:
        upload.media_file.close()


def render_movie_with_remotion(event, uploads, soundtrack, output_path, *, deliverable):
    """Rend un livrable (hero / full / teaser) via Remotion. Renvoie le chemin du MP4.

    Leve une exception si Node/Remotion echoue : l'appelant decide du fallback.
    """
    composition = COMPOSITIONS.get(deliverable)
    if not composition:
        raise ValueError(f"Livrable inconnu : {deliverable}")

    node_binary = shutil.which(settings.MEMORA_NODE_BINARY)
    if not node_binary:
        raise RuntimeError("Node introuvable : rendu Remotion impossible.")

    remotion_dir = Path(settings.MEMORA_REMOTION_DIR)
    render_script = remotion_dir / "render.mjs"
    if not render_script.exists():
        raise RuntimeError(f"Script de rendu absent : {render_script}")

    uploads = list(uploads)
    props = build_film_props(event, uploads, soundtrack)

    with tempfile.TemporaryDirectory(prefix="memora_remotion_") as work_dir:
        assets_dir = Path(work_dir) / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)

        # Materialise les clips (dans l'ordre des props) et la musique.
        for clip, upload in zip(props["clips"], uploads):
            _materialize_upload(upload, assets_dir / clip["src"])

        if props["audioSrc"]:
            track_path, cleanup = materialize_soundtrack(soundtrack, assets_dir)
            if track_path:
                shutil.copy(track_path, assets_dir / props["audioSrc"])
                if cleanup:
                    Path(track_path).unlink(missing_ok=True)
            else:
                props["audioSrc"] = None  # piste indisponible : on garde le silence

        props_path = Path(work_dir) / "props.json"
        props_path.write_text(json.dumps(props), encoding="utf-8")

        command = [
            node_binary,
            str(render_script),
            f"--composition={composition['id']}",
            f"--props={props_path}",
            f"--output={output_path}",
            f"--public-dir={assets_dir}",
        ]
        logger.info(
            "Remotion render started event=%s deliverable=%s clips=%s",
            event.pk,
            deliverable,
            len(uploads),
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
                f"Rendu Remotion echoue (code {result.returncode}) : "
                f"{(result.stderr or result.stdout or '').strip()[:500]}"
            )

    logger.info("Remotion render completed event=%s deliverable=%s", event.pk, deliverable)
    return Path(output_path)
