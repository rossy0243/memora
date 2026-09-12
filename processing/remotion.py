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
import random
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

# Rythme par livrable : le teaser est punchy (Ken Burns marque), l'integrale
# respire, le heros est equilibre.
_PACE_BY_DELIVERABLE = {
    "teaser": "punchy",
    "hero": "balanced",
    "full": "gentle",
}

# Duree de la transition (cross-dissolve) par rythme, en secondes. Un fondu
# fixe (l'ancien `fps/2`) rendait le teaser mou et l'integrale trop nerveuse
# pour son intention "on respire" — le fondu doit suivre le meme rythme que
# le Ken Burns (voir KEN_BURNS cote TSX).
_TRANSITION_SECONDS_BY_PACE = {
    "punchy": 10 / 30,
    "balanced": 15 / 30,
    "gentle": 22 / 30,
}

def _clip_keeps_audio(upload):
    """Vrai si le plan garde son audio : toute video. Le son des invites EST
    l'emotion — meme regle que le pipeline ffmpeg, qui mixe l'audio de tous les
    clips sous la musique ; le ducking gere l'equilibre. (Ne pas conditionner au
    tag « voix » : il n'est pose que par l'analyse Google, desactivee en prod.)"""
    return upload.media_type == GuestUpload.MediaType.VIDEO


def _seconds_to_frames(seconds, fps):
    return max(int(round(seconds * fps)), 1)


def _jittered_photo_seconds(base_seconds, seed):
    """Varie legerement la duree d'une photo, de facon deterministe (seed = pk de
    l'upload) : rejouer le rendu produit exactement le meme montage. Sans ca,
    chaque photo tenait *exactement* la meme duree — un motif mecanique qui se
    voit a l'oeil sur un film de plusieurs dizaines de plans. Une vraie monteuse
    varie le tempo ; +/-  jusqu'a 20% imite ca sans jamais assez pour desynchroniser
    le calage sur le tempo (snap_duration_to_beat corrige apres coup)."""
    rng = random.Random(seed or 0)
    factor = rng.uniform(0.85, 1.2)
    return max(base_seconds * factor, 0.1)


def _clip_seconds(upload, beat_interval):
    """Duree d'un plan, calee sur le tempo — meme logique que le pipeline ffmpeg."""
    from .services import snap_duration_to_beat

    if upload.media_type == GuestUpload.MediaType.IMAGE:
        base = _jittered_photo_seconds(settings.MEMORA_MOVIE_IMAGE_DURATION_SECONDS, upload.pk)
        return snap_duration_to_beat(base, beat_interval)

    base = settings.MEMORA_MOVIE_VIDEO_MAX_SECONDS
    if upload.duration:
        base = min(upload.duration.total_seconds(), base)
    snapped = snap_duration_to_beat(base, beat_interval)
    # On ne rallonge jamais un plan au-dela de sa duree reelle (sinon image gelee).
    if snapped > base and beat_interval:
        snapped = max(snapped - beat_interval, beat_interval)
    return snapped


def build_film_props(
    event, uploads, soundtrack, *, fps=None, pace="balanced", allow_guest_audio=False, deliverable=None
):
    """Construit le dict FilmProps (aligne avec remotion/src/types.ts).

    Les `src` sont des noms de fichiers relatifs au dossier d'assets materialise ;
    la piste musicale est nommee `music.<ext>`.
    """
    fps = fps or settings.MEMORA_REMOTION_FPS
    beat_interval = soundtrack.beat_interval if soundtrack else 0.0

    # Chapitres par horaire reel (debut/coeur/fin), pas par categorie : l'invite
    # ne choisit plus de moment, donc tout porte le meme code desormais.
    from .services import assign_time_chapters

    chapters = assign_time_chapters(list(uploads))

    clips = []
    for index, upload in enumerate(uploads, start=1):
        suffix = Path(upload.original_filename or upload.media_file.name).suffix.lower() or ".media"
        seconds = _clip_seconds(upload, beat_interval)
        category = getattr(upload, "category", None)
        _, chapter_label = chapters.get(upload.pk, (0, ""))
        clips.append(
            {
                "kind": "video" if upload.media_type == GuestUpload.MediaType.VIDEO else "image",
                "src": f"clip_{index:04d}{suffix}",
                "durationInFrames": _seconds_to_frames(seconds, fps),
                "category": getattr(category, "code", "") or "",
                "label": chapter_label,
                "keepAudio": bool(allow_guest_audio and _clip_keeps_audio(upload)),
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

    resolved_pace = pace if pace in ("punchy", "balanced", "gentle") else "balanced"

    return {
        "clips": clips,
        "audioSrc": audio_src,
        "audioFirstBeatOffset": audio_offset,
        "title": title or event.title,
        "subtitle": subtitle,
        "outroTitle": settings.MEMORA_MOVIE_OUTRO_TITLE or "Merci",
        "introDurationInFrames": _seconds_to_frames(settings.MEMORA_MOVIE_INTRO_CARD_SECONDS, fps),
        "outroDurationInFrames": _seconds_to_frames(settings.MEMORA_MOVIE_OUTRO_CARD_SECONDS, fps),
        "transitionDurationInFrames": _seconds_to_frames(
            _TRANSITION_SECONDS_BY_PACE.get(resolved_pace, 0.5), fps
        ),
        "grade": _GRADE_BY_MOOD.get(getattr(soundtrack, "mood", ""), "romantic"),
        "pace": resolved_pace,
        "musicVolume": float(getattr(settings, "MEMORA_REMOTION_MUSIC_VOLUME", 0.85)),
        "duckedMusicVolume": float(getattr(settings, "MEMORA_REMOTION_DUCKED_MUSIC_VOLUME", 0.10)),
        # Bandeaux cinema (2.35:1) : reserves au heros, l'effet "salle de cinema"
        # sur le livrable qu'on regarde ensemble, pas sur l'integrale (archive)
        # ni le teaser (deja vertical plein cadre).
        "cinematicBars": deliverable == "hero",
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


# Conteneur -> codec audio compatible pour le remux (webm n'accepte pas l'aac,
# mov/mp4 n'acceptent pas l'opus). MediaRecorder cote invite produit surtout du
# webm (vp9/vp8 + opus) ; mp4/mov arrivent plutot des cameras natives.
_AUDIO_CODEC_BY_CONTAINER = {
    ".webm": "libopus",
    ".mp4": "aac",
    ".mov": "aac",
}


def _normalize_clip_audio(path, ffmpeg_binary):
    """Aligne le niveau sonore d'un plan (loudness EBU R128) avant que Remotion
    ne le joue : sans ca, un discours filme de pres et une ambiance de piste de
    danse arrivent a des niveaux tres differents, et aucun ducking ne rattrape
    cet ecart tout seul. Remux audio uniquement (`-c:v copy`) : rapide, image
    intacte. Echec silencieux — un plan non normalise vaut mieux qu'un film en
    panne.
    """
    audio_codec = _AUDIO_CODEC_BY_CONTAINER.get(path.suffix.lower(), "aac")
    normalized_path = path.with_name(path.stem + ".normalized" + path.suffix)
    command = [
        ffmpeg_binary,
        "-y",
        "-i",
        str(path),
        "-c:v",
        "copy",
        "-af",
        "loudnorm=I=-16:TP=-1.5:LRA=11",
        "-c:a",
        audio_codec,
        str(normalized_path),
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=60)
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.warning("Normalisation audio ignoree pour %s : %s", path.name, exc)
        return
    if result.returncode == 0 and normalized_path.exists():
        normalized_path.replace(path)
    else:
        logger.warning(
            "Normalisation audio ignoree pour %s : %s",
            path.name,
            (result.stderr or "").strip()[:300],
        )
        normalized_path.unlink(missing_ok=True)


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
    pace = _PACE_BY_DELIVERABLE.get(deliverable, "balanced")
    props = build_film_props(
        event,
        uploads,
        soundtrack,
        pace=pace,
        allow_guest_audio=deliverable in settings.MEMORA_REMOTION_GUEST_AUDIO_DELIVERABLES,
        deliverable=deliverable,
    )

    with tempfile.TemporaryDirectory(prefix="memora_remotion_") as work_dir:
        assets_dir = Path(work_dir) / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)

        # Materialise les clips (dans l'ordre des props) et la musique.
        for clip, upload in zip(props["clips"], uploads):
            destination = assets_dir / clip["src"]
            _materialize_upload(upload, destination)
            if clip["kind"] == "video" and clip["keepAudio"]:
                _normalize_clip_audio(destination, settings.MEMORA_FFMPEG_BINARY)

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
