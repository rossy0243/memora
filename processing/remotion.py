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
import time
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist

from uploads.models import GuestUpload

from .analysis import get_analysis_score
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

# Categories festives/energiques : reservoir du mini-collage de fin (voir
# _select_highlight_uploads). "party" n'existe pas cote catalogue reel — seules
# ces trois categories sont effectivement seedees (uploads/services.py).
_HIGHLIGHT_CATEGORY_CODES = {"dancefloor", "cake", "funny"}


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


def _exposure_correction(upload):
    """Correction douce de luminosite (multiplicateur CSS `brightness()`) a partir
    du score deja calcule par l'analyse locale (processing.analysis). Cible 55
    (voir _score_upload) : une photo de soiree trop sombre remonte un peu, une
    photo cramee redescend — sans repeindre l'accord colorimetrique du plan.
    Bornee a +/-25% : correctrice, jamais un filtre qui se voit."""
    try:
        brightness = upload.analysis.brightness
    except (ObjectDoesNotExist, AttributeError):
        # ObjectDoesNotExist : upload reel, analyse pas encore faite.
        # AttributeError : upload de test (SimpleNamespace) sans champ `brightness`.
        return 1.0
    if brightness is None:
        return 1.0
    correction = 1 + (55 - brightness) / 180
    return round(max(0.85, min(correction, 1.25)), 3)


def _select_highlight_uploads(uploads, limit=3):
    """Meilleures photos festives (dancefloor/gateau/moment drole) parmi celles
    deja retenues pour ce montage — pour le mini-collage de fin. En dessous de 2
    candidats, pas de collage : mieux vaut l'omettre qu'un montage chiche."""
    candidates = [
        upload
        for upload in uploads
        if upload.media_type == GuestUpload.MediaType.IMAGE
        and getattr(getattr(upload, "category", None), "code", "") in _HIGHLIGHT_CATEGORY_CODES
    ]
    scored = sorted(candidates, key=lambda upload: get_analysis_score(upload) or 0, reverse=True)
    selected = scored[:limit]
    return selected if len(selected) >= 2 else []


def _select_cold_open_index(uploads):
    """Index (dans `uploads`, donc dans `clips`) du plan choisi pour l'ouverture a
    froid. Priorite au meilleur score (processing.analysis) plutot qu'au premier
    plan chronologique — sans analyse disponible, on retombe sur le tout premier."""
    best_index = 0
    best_score = None
    for index, upload in enumerate(uploads):
        score = get_analysis_score(upload)
        if score is not None and (best_score is None or score > best_score):
            best_score = score
            best_index = index
    return best_index


def _event_stats(event):
    """Chiffres de participation reels de l'evenement (pas seulement les plans
    retenus pour ce montage) : le carton doit refleter toute la collecte, pas
    le sous-ensemble monte cette fois-ci. `event` peut etre un double de test
    (SimpleNamespace) sans relation `guest_uploads` : dans ce cas, pas de carton."""
    guest_uploads = getattr(event, "guest_uploads", None)
    if guest_uploads is None:
        return None

    approved = guest_uploads.filter(
        is_deleted=False, moderation_status=GuestUpload.ModerationStatus.APPROVED
    )
    total = approved.count()
    if not total:
        return None
    contributors = (
        approved.exclude(session_key="").values("session_key").distinct().count()
    )
    return {"totalMemories": total, "contributors": contributors}


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
    src_by_upload_pk = {}
    for index, upload in enumerate(uploads, start=1):
        suffix = Path(upload.original_filename or upload.media_file.name).suffix.lower() or ".media"
        seconds = _clip_seconds(upload, beat_interval)
        category = getattr(upload, "category", None)
        _, chapter_label = chapters.get(upload.pk, (0, ""))
        src = f"clip_{index:04d}{suffix}"
        src_by_upload_pk[upload.pk] = src
        clips.append(
            {
                "kind": "video" if upload.media_type == GuestUpload.MediaType.VIDEO else "image",
                "src": src,
                "durationInFrames": _seconds_to_frames(seconds, fps),
                "category": getattr(category, "code", "") or "",
                "label": chapter_label,
                "keepAudio": bool(allow_guest_audio and _clip_keeps_audio(upload)),
                "brightnessCorrection": _exposure_correction(upload),
            }
        )

    title, subtitle = event_intro_texts(event)

    # Cartons additionnels : Hero/Full seulement — le Teaser doit rester court et
    # percutant, sans les ralentir avec un mot des maries ou un recap en chiffres.
    include_extra_cards = deliverable != "teaser"
    welcome_message = (getattr(event, "welcome_message", "") or "").strip() if include_extra_cards else ""
    stats = _event_stats(event) if include_extra_cards else None
    highlight_uploads = _select_highlight_uploads(uploads) if include_extra_cards else []
    highlight_clips = [
        {"kind": "image", "src": src_by_upload_pk[upload.pk]} for upload in highlight_uploads
    ]

    audio_src = None
    audio_offset = 0.0
    if soundtrack and soundtrack.has_track:
        # track_extension (piste DB / musique personnalisee) reflete le VRAI
        # format du fichier : sans elle, un .wav/.m4a se retrouvait copie sous un
        # nom "music.mp3" trompeur, et le Content-Type servi a Remotion avec.
        audio_ext = getattr(soundtrack, "track_extension", "") or ".mp3"
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
        # Logo permanent en haut a droite, avec le mot « Memora », sur tous les livrables :
        # la marque reste visible du debut a la fin (et pas seulement sur le sceau du carton
        # final), pour ceux qui ne connaissent pas le monogramme.
        "watermark": True,
        # Ouverture a froid : quel plan (index dans `clips`) sert de fond muet au
        # carton d'intro. Le meilleur score plutot que le premier chronologique —
        # voir _select_cold_open_index.
        "coldOpenClipIndex": _select_cold_open_index(uploads),
        # Mot des maries : vide si le champ event.welcome_message ne contient rien,
        # ou sur le Teaser (voir include_extra_cards ci-dessus).
        "welcomeMessage": welcome_message,
        "welcomeMessageDurationInFrames": _seconds_to_frames(
            settings.MEMORA_MOVIE_MESSAGE_CARD_SECONDS, fps
        ),
        # Recap en chiffres (participation reelle de l'evenement) : null si aucun
        # souvenir approuve, ou sur le Teaser.
        "stats": stats,
        "statsDurationInFrames": _seconds_to_frames(settings.MEMORA_MOVIE_STATS_CARD_SECONDS, fps),
        # Mini-collage des meilleurs moments festifs : liste vide si moins de 2
        # candidats trouves, ou sur le Teaser.
        "highlightClips": highlight_clips,
        "highlightDurationInFrames": _seconds_to_frames(
            settings.MEMORA_MOVIE_HIGHLIGHT_CARD_SECONDS, fps
        ),
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


def run_remotion_subprocess(command, *, cwd, timeout, progress_path=None, progress_callback=None, failure_label="Rendu Remotion"):
    """Lance `node render.mjs` et attend la fin, en sondant la progression.

    Boucle de sondage plutot qu'un simple `run(..., timeout=...)` : c'est ce
    qui laisse la main entre deux attentes pour lire le fichier de progression
    et appeler `progress_callback`, tout en gardant le meme comportement de
    timeout global (le process est tue si `timeout` est depasse). Partage par
    tous les rendus Remotion (film souvenir et montage du livre d'or).
    """
    started_at = time.monotonic()
    last_reported = None
    process = subprocess.Popen(
        command,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    while True:
        try:
            stdout, stderr = process.communicate(timeout=2)
            break
        except subprocess.TimeoutExpired:
            if progress_callback and progress_path and progress_path.exists():
                try:
                    fraction = json.loads(progress_path.read_text(encoding="utf-8")).get("progress")
                except (OSError, ValueError):
                    fraction = None
                if fraction is not None and fraction != last_reported:
                    last_reported = fraction
                    progress_callback(fraction)
            if time.monotonic() - started_at > timeout:
                process.kill()
                process.communicate()
                raise RuntimeError(f"{failure_label} : delai depasse ({timeout}s).")

    if process.returncode != 0:
        raise RuntimeError(
            f"{failure_label} echoue (code {process.returncode}) : "
            f"{(stderr or stdout or '').strip()[:500]}"
        )
    return stdout


def render_movie_with_remotion(event, uploads, soundtrack, output_path, *, deliverable, progress_callback=None):
    """Rend un livrable (hero / full / teaser) via Remotion. Renvoie le chemin du MP4.

    Leve une exception si Node/Remotion echoue : l'appelant decide du fallback.

    `progress_callback(fraction)`, si fourni, est appele periodiquement pendant le
    rendu avec l'avancement reel (0.0 a 1.0, voir render.mjs/onProgress) — permet
    de remonter une progression qui bouge vraiment cote organisateur, plutot qu'un
    pourcentage fige pendant toute la duree (potentiellement plusieurs minutes) du
    rendu Chrome headless.
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
        progress_path = Path(work_dir) / "progress.json"

        command = [
            node_binary,
            str(render_script),
            f"--composition={composition['id']}",
            f"--props={props_path}",
            f"--output={output_path}",
            f"--public-dir={assets_dir}",
            f"--progress-file={progress_path}",
        ]
        logger.info(
            "Remotion render started event=%s deliverable=%s clips=%s",
            event.pk,
            deliverable,
            len(uploads),
        )

        run_remotion_subprocess(
            command,
            cwd=remotion_dir,
            timeout=settings.MEMORA_REMOTION_TIMEOUT_SECONDS,
            progress_path=progress_path,
            progress_callback=progress_callback,
            failure_label="Rendu Remotion",
        )

    logger.info("Remotion render completed event=%s deliverable=%s", event.pk, deliverable)
    return Path(output_path)
