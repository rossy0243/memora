"""Montage integral du livre d'or : pipeline hybride Remotion + FFmpeg.

Livrable distinct du film souvenir : tous les messages video des invites, en
entier, dans l'ordre chronologique, chacun precede d'un carton « De la part
de … ».

Pourquoi hybride : le rendu 100 % Remotion jouait chaque message deux fois
(fond floute + plan net) avec un flou plein cadre a chaque image, dans un Chrome
sans carte graphique — des heures pour quelques dizaines de messages. Ici :
  - les cartons (titre, noms, fin) restent dessines par Remotion, mais en IMAGES
    FIXES rendues en une seule passe (`render-cards.mjs`) : le meme rendu
    typographique, en quelques secondes ;
  - chaque message est passe dans FFmpeg (cadrage contain sur fond floute, grade,
    loudness, fondus), plusieurs a la fois ;
  - l'assemblage est une concatenation sans reencodage, puis un mixage musical
    dont le niveau baisse sous chaque message (la voix passe avant la musique).
Une version legere 720p est produite dans la foulee pour le telephone.
"""
import json
import logging
import os
import shutil
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.utils import timezone

from .remotion import _materialize_upload, run_remotion_subprocess
from .soundtrack import choose_movie_soundtrack, materialize_soundtrack

logger = logging.getLogger(__name__)

FPS = 30
WIDTH = 1920
HEIGHT = 1080
LIGHT_HEIGHT = 720
# Fondu (entrant et sortant) de chaque segment : un « passage par le noir » entre
# le carton et le message, peu couteux et propre a la lecture.
FADE_SECONDS = 0.5
VOICE_FADE_SECONDS = 0.2
# Qualite du fichier HD (x264) : plafonne pour rester telechargeable en mobilite.
HD_CRF = 23
HD_MAX_KBPS = 5000
LIGHT_CRF = 27
LIGHT_MAX_KBPS = 1800
SEGMENT_TIMEOUT_SECONDS = 900
ASSEMBLY_TIMEOUT_SECONDS = 1800

# Etalonnage par ambiance musicale : (saturation, decalage U, decalage V). Meme
# intention que MOOD_COLOR_GRADE_FILTERS du film, mais en `hue` + table de
# correspondance YUV : `colorbalance` coutait a lui seul ~75 % du temps d'encodage
# d'un message (8 s sur 10 pour un clip de 6 s). U bas / V haut = teinte chaude.
_GRADE_BY_MOOD = {
    "romantic_cinematic": (1.08, -3, 4),
    "cinematic_emotional": (0.85, 3, -1),
    "joyful_party": (1.25, -1, 3),
    "warm_lounge": (1.05, -4, 4),
    "elegant_warm": (1.05, -2, 3),
}
_FALLBACK_GRADE_MOOD = "elegant_warm"


@dataclass
class MontageResult:
    output_path: Path
    light_path: Path | None
    duration_seconds: float


class MontageError(RuntimeError):
    pass


def _update_guestbook_progress(movie, percent, message):
    movie.progress_percent = max(0.0, min(round(float(percent), 1), 100.0))
    movie.progress_message = message[:160]
    movie.save(update_fields=["progress_percent", "progress_message", "updated_at"])


# --- Outils FFmpeg ----------------------------------------------------------------


def _ffprobe_binary():
    return settings.MEMORA_FFPROBE_BINARY


def _run_ffmpeg(command, *, timeout, total_seconds=None, on_progress=None):
    """Lance FFmpeg ; leve MontageError avec la fin de stderr en cas d'echec.

    Si `on_progress` est fourni, FFmpeg ecrit son avancement sur stdout
    (`-progress pipe:1`) et `on_progress(fraction)` est appele au fil de l'eau :
    un encodage de plusieurs minutes ne doit pas laisser la barre figee.
    """
    command = [command[0], "-hide_banner", "-loglevel", "error", "-nostats", *command[1:]]
    if on_progress and total_seconds:
        command = [command[0], "-progress", "pipe:1", *command[1:]]

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    timed_out = threading.Event()

    def _kill():
        timed_out.set()
        process.kill()

    watchdog = threading.Timer(timeout, _kill)
    watchdog.start()
    stderr_chunks = []
    stderr_reader = threading.Thread(
        target=lambda: stderr_chunks.append(process.stderr.read()), daemon=True
    )
    stderr_reader.start()
    try:
        for line in process.stdout:
            if on_progress and total_seconds and line.startswith("out_time_us="):
                try:
                    seconds = int(line.split("=", 1)[1]) / 1_000_000
                except ValueError:
                    continue
                on_progress(max(0.0, min(seconds / total_seconds, 1.0)))
        process.wait()
    finally:
        watchdog.cancel()
        stderr_reader.join(timeout=5)

    if timed_out.is_set():
        raise MontageError(f"FFmpeg : delai depasse ({timeout}s).")
    if process.returncode != 0:
        details = "".join(stderr_chunks).strip()
        raise MontageError(f"FFmpeg a echoue (code {process.returncode}) : {details[-600:]}")


def _probe_duration(path):
    """Duree reelle d'un media, ou None. Un webm de MediaRecorder n'annonce
    souvent pas sa duree : on retombe alors sur le dernier horodatage de paquet."""
    binary = _ffprobe_binary()
    try:
        result = subprocess.run(
            [binary, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        value = (result.stdout or "").strip().splitlines()[0] if result.stdout.strip() else ""
        if result.returncode == 0 and value not in ("", "N/A"):
            duration = float(value)
            if duration > 0:
                return duration

        result = subprocess.run(
            [
                binary, "-v", "error", "-select_streams", "v:0",
                "-show_entries", "packet=pts_time", "-of", "csv=p=0", str(path),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        times = []
        for raw in (result.stdout or "").splitlines():
            try:
                times.append(float(raw.strip().rstrip(",")))
            except ValueError:
                continue
        if times:
            return max(times) + 1.0 / FPS
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None
    return None


def _has_audio_stream(path):
    try:
        result = subprocess.run(
            [
                _ffprobe_binary(), "-v", "error", "-select_streams", "a:0",
                "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(path),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and "audio" in result.stdout.lower()


def _video_encode_args(encoder, *, crf, max_kbps, threads=None):
    """Reglages d'encodage. x264 : CRF plafonne ; autres encodeurs (openh264 en
    local) : debit moyen, qui les accepte tous."""
    thread_args = ["-threads", str(threads)] if threads else []
    if encoder == "libx264":
        return [
            "-c:v", "libx264",
            "-preset", getattr(settings, "MEMORA_GUESTBOOK_MONTAGE_PRESET", "veryfast"),
            "-crf", str(crf),
            "-maxrate", f"{max_kbps}k",
            "-bufsize", f"{max_kbps * 2}k",
            "-pix_fmt", "yuv420p",
            *thread_args,
        ]
    return ["-c:v", encoder, "-b:v", f"{int(max_kbps * 0.6)}k", "-pix_fmt", "yuv420p", *thread_args]


_AUDIO_ARGS = ["-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2"]


def _grade_filter(soundtrack):
    if not settings.MEMORA_MOVIE_COLOR_GRADE_ENABLED:
        return "null"
    mood = getattr(soundtrack, "mood", "") or _FALLBACK_GRADE_MOOD
    saturation, shift_u, shift_v = _GRADE_BY_MOOD.get(mood, _GRADE_BY_MOOD[_FALLBACK_GRADE_MOOD])
    return (
        f"hue=s={saturation},"
        f"lutyuv=u='clip(val{shift_u:+d},0,255)':v='clip(val{shift_v:+d},0,255)'"
    )


# --- Segments ---------------------------------------------------------------------


def _message_seconds(message):
    """Duree annoncee du message (base), plafonnee. Le livre d'or est integral :
    on ne coupe que ce qui depasserait largement la duree maximale d'enregistrement."""
    ceiling = settings.MEMORA_GUESTBOOK_MAX_VIDEO_DURATION_SECONDS * 2
    if message.duration:
        return max(min(message.duration.total_seconds(), ceiling), 1.0)
    return float(settings.MEMORA_GUESTBOOK_MAX_VIDEO_DURATION_SECONDS)


def _encode_message_segment(source, destination, *, fallback_seconds, grade, encoder, threads):
    """Un message -> un segment 1080p30 : cadre contain sur fond floute (pas de
    bandes noires), grade, loudness, fondus. Renvoie la duree du segment."""
    ceiling = settings.MEMORA_GUESTBOOK_MAX_VIDEO_DURATION_SECONDS * 2
    measured = _probe_duration(source)
    duration = min(measured if measured else fallback_seconds, ceiling)
    duration = max(duration, 1.0)
    fade_out_at = max(duration - FADE_SECONDS, 0.0)
    voice_out_at = max(duration - VOICE_FADE_SECONDS, 0.0)

    video_graph = (
        f"[0:v]fps={FPS},split=2[bgsrc][fgsrc];"
        f"[bgsrc]scale=480:270:force_original_aspect_ratio=increase,crop=480:270,"
        f"gblur=sigma=6,colorchannelmixer=rr=0.45:gg=0.45:bb=0.45,scale={WIDTH}:{HEIGHT},setsar=1[bg];"
        f"[fgsrc]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease:force_divisible_by=2,setsar=1[fg];"
        f"[bg][fg]overlay=(W-w)/2:(H-h)/2,{grade},format=yuv420p,"
        f"fade=t=in:st=0:d={FADE_SECONDS},fade=t=out:st={fade_out_at:.3f}:d={FADE_SECONDS}[v]"
    )

    has_audio = _has_audio_stream(source)
    inputs = ["-i", str(source)]
    if has_audio:
        audio_graph = (
            "[0:a]loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000,"
            "aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"afade=t=in:st=0:d={VOICE_FADE_SECONDS},afade=t=out:st={voice_out_at:.3f}:d={VOICE_FADE_SECONDS},"
            f"apad,atrim=0:{duration:.3f}[a]"
        )
    else:
        inputs += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
        audio_graph = f"[1:a]atrim=0:{duration:.3f}[a]"

    _run_ffmpeg(
        [
            settings.MEMORA_FFMPEG_BINARY, "-y", *inputs,
            "-filter_complex", f"{video_graph};{audio_graph}",
            "-map", "[v]", "-map", "[a]",
            *_video_encode_args(encoder, crf=HD_CRF, max_kbps=HD_MAX_KBPS, threads=threads),
            *_AUDIO_ARGS,
            "-t", f"{duration:.3f}",
            str(destination),
        ],
        timeout=SEGMENT_TIMEOUT_SECONDS,
    )
    return _probe_duration(destination) or duration


def _encode_card_segment(card_png, destination, *, seconds, encoder, threads):
    """Un carton (image fixe) -> segment video avec fondu entrant/sortant, muet."""
    fade_out_at = max(seconds - FADE_SECONDS, 0.0)
    _run_ffmpeg(
        [
            settings.MEMORA_FFMPEG_BINARY, "-y",
            "-loop", "1", "-framerate", str(FPS), "-t", f"{seconds:.3f}", "-i", str(card_png),
            "-f", "lavfi", "-t", f"{seconds:.3f}", "-i", "anullsrc=r=48000:cl=stereo",
            "-vf",
            f"scale={WIDTH}:{HEIGHT},setsar=1,format=yuv420p,"
            f"fade=t=in:st=0:d={FADE_SECONDS},fade=t=out:st={fade_out_at:.3f}:d={FADE_SECONDS}",
            "-map", "0:v", "-map", "1:a",
            *_video_encode_args(encoder, crf=HD_CRF, max_kbps=HD_MAX_KBPS, threads=threads),
            *_AUDIO_ARGS,
            "-t", f"{seconds:.3f}",
            str(destination),
        ],
        timeout=SEGMENT_TIMEOUT_SECONDS,
    )
    return _probe_duration(destination) or seconds


# --- Cartons (Remotion, images fixes) ---------------------------------------------


def _card_specs(event, messages, work_dir):
    fps = settings.MEMORA_REMOTION_FPS or FPS

    def frames(seconds):
        return max(int(round(seconds * fps)), 1)

    def still_frame(duration_in_frames):
        # Toutes les animations d'entree sont finies, la sortie n'a pas commence.
        return max(min(duration_in_frames // 2, duration_in_frames - 16), 1)

    intro_frames = frames(settings.MEMORA_GUESTBOOK_MONTAGE_INTRO_CARD_SECONDS)
    name_frames = frames(settings.MEMORA_GUESTBOOK_MONTAGE_NAME_CARD_SECONDS)
    outro_frames = frames(settings.MEMORA_GUESTBOOK_MONTAGE_OUTRO_CARD_SECONDS)

    def spec(name, frames_count, props):
        return {
            "output": str(work_dir / f"{name}.png"),
            "frame": still_frame(frames_count),
            "props": {**props, "durationInFrames": frames_count},
        }

    empty = {"title": "", "subtitle": "", "name": ""}
    cards = {
        "intro": spec("card_intro", intro_frames, {**empty, "kind": "intro", "title": event.title, "subtitle": "Livre d'or"}),
        "outro": spec(
            "card_outro", outro_frames,
            {**empty, "kind": "outro", "title": settings.MEMORA_GUESTBOOK_MONTAGE_OUTRO_TITLE or "Merci", "subtitle": event.title},
        ),
        "names": [
            spec(f"card_name_{index:04d}", name_frames, {**empty, "kind": "name", "name": (message.guest_name or "").strip()})
            for index, message in enumerate(messages, start=1)
        ],
    }
    return cards


def _render_cards(cards, work_dir, assets_dir, progress_callback):
    node_binary = shutil.which(settings.MEMORA_NODE_BINARY)
    if not node_binary:
        raise MontageError("Node introuvable : rendu des cartons impossible.")
    remotion_dir = Path(settings.MEMORA_REMOTION_DIR)
    script = remotion_dir / "render-cards.mjs"
    if not script.exists():
        raise MontageError(f"Script de rendu absent : {script}")

    specs = [cards["intro"], *cards["names"], cards["outro"]]
    cards_path = work_dir / "cards.json"
    cards_path.write_text(json.dumps(specs), encoding="utf-8")
    progress_path = work_dir / "cards_progress.json"

    output = run_remotion_subprocess(
        [
            node_binary, str(script),
            f"--cards={cards_path}",
            f"--public-dir={assets_dir}",
            f"--progress-file={progress_path}",
        ],
        cwd=remotion_dir,
        timeout=settings.MEMORA_REMOTION_TIMEOUT_SECONDS,
        progress_path=progress_path,
        progress_callback=progress_callback,
        failure_label="Rendu des cartons du livre d'or",
    )
    for line in (output or "").splitlines():
        if line.startswith("TIMINGS"):
            logger.info("Guestbook cards %s", line)


# --- Musique ----------------------------------------------------------------------


def _music_gain_expression(voice_windows, bed, ducked, ramp=1.0 / 3):
    """Volume de la musique dans le temps : `bed` sur les cartons, `ducked` sous
    chaque message, avec une rampe de ~330 ms de chaque cote (meme courbe que le
    montage Remotion d'origine). Les fenetres ne se chevauchent pas — un carton
    de plusieurs secondes separe deux messages — donc les creux s'additionnent."""
    if not voice_windows:
        return f"{bed:.4f}"
    terms = "+".join(
        f"clip(min((t-{start - ramp:.3f})/{ramp:.3f},({end + ramp:.3f}-t)/{ramp:.3f}),0,1)"
        for start, end in voice_windows
    )
    return f"{bed:.4f}-{bed - ducked:.4f}*({terms})"


def _assemble(segments, voice_windows, total_seconds, music_path, music_offset, output_path, work_dir, progress_callback):
    list_path = work_dir / "segments.txt"
    list_path.write_text(
        "".join(f"file '{Path(path).as_posix()}'\n" for path in segments), encoding="utf-8"
    )
    ffmpeg = settings.MEMORA_FFMPEG_BINARY

    if not music_path:
        _run_ffmpeg(
            [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(list_path),
             "-c", "copy", "-movflags", "+faststart", str(output_path)],
            timeout=ASSEMBLY_TIMEOUT_SECONDS,
        )
        return

    bed = float(settings.MEMORA_GUESTBOOK_MONTAGE_MUSIC_VOLUME)
    ducked = float(settings.MEMORA_GUESTBOOK_MONTAGE_DUCKED_MUSIC_VOLUME)
    gain = _music_gain_expression(voice_windows, bed, ducked)
    fade_out_at = max(total_seconds - 3.0, 0.0)
    music_graph = (
        "[1:a]aformat=sample_fmts=fltp:channel_layouts=stereo,aresample=48000,"
        f"volume='{gain}':eval=frame,afade=t=in:st=0:d=1.5,afade=t=out:st={fade_out_at:.3f}:d=3[music];"
        "[0:a][music]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]"
    )
    music_input = ["-stream_loop", "-1"]
    if music_offset:
        music_input += ["-ss", f"{music_offset:.3f}"]
    _run_ffmpeg(
        [
            ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(list_path),
            *music_input, "-i", str(music_path),
            "-filter_complex", music_graph,
            "-map", "0:v", "-map", "[a]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2",
            "-t", f"{total_seconds:.3f}",
            "-movflags", "+faststart",
            str(output_path),
        ],
        timeout=ASSEMBLY_TIMEOUT_SECONDS,
        total_seconds=total_seconds,
        on_progress=progress_callback,
    )


def _encode_light_version(source, destination, total_seconds, progress_callback):
    """Version 720p legere pour le telephone (4G, forfait limite)."""
    encoder = settings.MEMORA_MOVIE_VIDEO_ENCODER
    _run_ffmpeg(
        [
            settings.MEMORA_FFMPEG_BINARY, "-y", "-i", str(source),
            "-vf", f"scale=-2:{LIGHT_HEIGHT}",
            *_video_encode_args(encoder, crf=LIGHT_CRF, max_kbps=LIGHT_MAX_KBPS),
            "-c:a", "aac", "-b:a", "96k", "-ac", "2",
            "-movflags", "+faststart",
            str(destination),
        ],
        timeout=ASSEMBLY_TIMEOUT_SECONDS,
        total_seconds=total_seconds,
        on_progress=progress_callback,
    )


# --- Orchestration ----------------------------------------------------------------


def _available_cpus():
    """Coeurs reellement utilisables. `os.cpu_count()` renvoie ceux de la machine
    hote, pas le quota du conteneur : sur Render il annonce 8 a 16 coeurs pour un
    service qui en a 4, et on lancait alors deux fois trop d'encodages (memoire
    et temps gaspilles a se disputer les memes coeurs)."""
    count = os.cpu_count() or 1
    try:
        count = min(count, len(os.sched_getaffinity(0)))
    except AttributeError:
        pass
    try:  # cgroup v2
        quota, period = Path("/sys/fs/cgroup/cpu.max").read_text().split()
        if quota != "max":
            count = min(count, max(1, -(-int(quota) // int(period))))
    except (OSError, ValueError):
        pass
    try:  # cgroup v1
        quota = int(Path("/sys/fs/cgroup/cpu/cpu.cfs_quota_us").read_text())
        period = int(Path("/sys/fs/cgroup/cpu/cpu.cfs_period_us").read_text())
        if quota > 0:
            count = min(count, max(1, -(-quota // period)))
    except (OSError, ValueError):
        pass
    return max(1, count)


def _worker_count():
    configured = getattr(settings, "MEMORA_GUESTBOOK_MONTAGE_WORKERS", 0)
    if configured and configured > 0:
        return configured
    # Deux coeurs par encodage ; plafonne : chaque encodage 1080p pese ~400 Mo.
    return max(1, min(_available_cpus() // 2, 4))


def render_guestbook_montage(event, messages, output_path, light_output_path=None, progress_callback=None):
    """Produit le montage (et, si demande, sa version legere). Renvoie un MontageResult.

    `progress_callback(fraction, message)` est appele au fil des etapes avec
    l'avancement global (0.0 a 1.0). Leve une exception si une etape echoue :
    l'appelant gere l'echec.
    """
    messages = list(messages)
    if not messages:
        raise ValueError("Aucun message de livre d'or a monter.")

    def report(fraction, message):
        if progress_callback:
            progress_callback(max(0.0, min(fraction, 1.0)), message)

    encoder = settings.MEMORA_MOVIE_VIDEO_ENCODER
    workers = _worker_count()
    threads_per_encode = max(1, _available_cpus() // workers)
    soundtrack = choose_movie_soundtrack(event, [])
    grade = _grade_filter(soundtrack)

    logger.info(
        "Guestbook montage started event=%s messages=%s workers=%s", event.pk, len(messages), workers
    )

    with tempfile.TemporaryDirectory(prefix="memora_guestbook_") as work_root:
        work_dir = Path(work_root)
        assets_dir = work_dir / "assets"
        segments_dir = work_dir / "segments"
        assets_dir.mkdir()
        segments_dir.mkdir()

        # 1. Materialisation des messages (R2 -> disque), en parallele.
        report(0.0, "Préparation des messages.")
        sources = []
        for index, message in enumerate(messages, start=1):
            suffix = Path(message.original_filename or message.media_file.name).suffix.lower() or ".mp4"
            sources.append(assets_dir / f"message_{index:04d}{suffix}")
        with ThreadPoolExecutor(max_workers=min(6, len(messages))) as pool:
            futures = {
                pool.submit(_materialize_upload, message, destination): destination
                for message, destination in zip(messages, sources)
            }
            done = 0
            for future in as_completed(futures):
                future.result()
                done += 1
                report(0.08 * done / len(messages), f"Préparation des messages ({done}/{len(messages)}).")

        # 2. Cartons Remotion, images fixes, une seule passe.
        report(0.08, "Création des cartons de nom.")
        cards = _card_specs(event, messages, work_dir)
        _render_cards(
            cards, work_dir, assets_dir,
            lambda fraction: report(0.08 + 0.17 * fraction, "Création des cartons de nom."),
        )

        # 3. Segments : cartons + messages, plusieurs FFmpeg a la fois.
        intro_seconds = float(settings.MEMORA_GUESTBOOK_MONTAGE_INTRO_CARD_SECONDS)
        name_seconds = float(settings.MEMORA_GUESTBOOK_MONTAGE_NAME_CARD_SECONDS)
        outro_seconds = float(settings.MEMORA_GUESTBOOK_MONTAGE_OUTRO_CARD_SECONDS)

        jobs = [("intro", segments_dir / "seg_0000_intro.mp4", cards["intro"]["output"], intro_seconds, None)]
        for index, (message, source) in enumerate(zip(messages, sources), start=1):
            jobs.append(("name", segments_dir / f"seg_{index:04d}_a_name.mp4", cards["names"][index - 1]["output"], name_seconds, None))
            jobs.append(("message", segments_dir / f"seg_{index:04d}_b_message.mp4", source, None, message))
        jobs.append(("outro", segments_dir / "seg_9999_outro.mp4", cards["outro"]["output"], outro_seconds, None))

        durations = {}
        message_total = len(messages)
        messages_done = 0

        def run_job(job):
            kind, destination, source, seconds, message = job
            if kind == "message":
                return destination, _encode_message_segment(
                    source, destination,
                    fallback_seconds=_message_seconds(message),
                    grade=grade, encoder=encoder, threads=threads_per_encode,
                )
            return destination, _encode_card_segment(
                source, destination, seconds=seconds, encoder=encoder, threads=threads_per_encode
            )

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(run_job, job): job for job in jobs}
            try:
                for future in as_completed(futures):
                    destination, duration = future.result()
                    durations[destination] = duration
                    if futures[future][0] == "message":
                        messages_done += 1
                        report(
                            0.25 + 0.55 * messages_done / message_total,
                            f"Montage des messages ({messages_done}/{message_total}).",
                        )
            except Exception:
                for pending in futures:
                    pending.cancel()
                raise

        ordered = [job[1] for job in jobs]
        timeline = 0.0
        voice_windows = []
        for job in jobs:
            length = durations[job[1]]
            if job[0] == "message":
                voice_windows.append((timeline, timeline + length))
            timeline += length
        total_seconds = timeline

        # 4. Assemblage sans reencodage + musique baissee sous les voix.
        report(0.80, "Assemblage et musique.")
        music_path = None
        cleanup = False
        if soundtrack and soundtrack.has_track:
            music_path, cleanup = materialize_soundtrack(soundtrack, assets_dir)
        try:
            _assemble(
                ordered, voice_windows, total_seconds,
                music_path, float(getattr(soundtrack, "first_beat_offset", 0.0) or 0.0),
                output_path, work_dir,
                lambda fraction: report(0.80 + 0.10 * fraction, "Assemblage et musique."),
            )
        finally:
            if music_path and cleanup:
                Path(music_path).unlink(missing_ok=True)

        # 5. Version legere : un echec ici ne doit jamais perdre le montage HD.
        light_path = None
        if light_output_path:
            report(0.90, "Version légère pour téléphone.")
            try:
                _encode_light_version(
                    output_path, light_output_path, total_seconds,
                    lambda fraction: report(0.90 + 0.10 * fraction, "Version légère pour téléphone."),
                )
                light_path = Path(light_output_path)
            except Exception:
                logger.exception("Guestbook light version failed event=%s", event.pk)
                Path(light_output_path).unlink(missing_ok=True)

    logger.info(
        "Guestbook montage completed event=%s duration=%.0fs light=%s",
        event.pk, total_seconds, bool(light_path),
    )
    return MontageResult(Path(output_path), light_path, total_seconds)


def _delete_previous_files(movie, previous_names):
    """Apres un nouveau montage, supprime l'ancien fichier : sinon chaque
    regeneration laisse un fichier orphelin de plusieurs centaines de Mo sur R2."""
    for field_name, old_name in previous_names.items():
        current = getattr(movie, field_name)
        if not old_name or (current and current.name == old_name):
            continue
        try:
            getattr(movie, field_name).storage.delete(old_name)
        except Exception:
            logger.warning("Guestbook montage old file not deleted name=%s", old_name, exc_info=True)


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
    _update_guestbook_progress(movie, 2, "Préparation du montage.")

    # Fenetre 2-96 % pour le travail ; le reste est l'envoi des fichiers vers R2.
    # FFmpeg publie sa progression plusieurs fois par seconde : on n'ecrit en base
    # que si le chiffre ou le texte a change de facon visible.
    last_saved = {"at": 0.0, "percent": -1.0, "message": ""}

    def _report(fraction, message):
        percent = 2 + fraction * 94
        now = time.monotonic()
        moved = abs(percent - last_saved["percent"]) >= 0.5
        if message == last_saved["message"] and not moved and now - last_saved["at"] < 3.0:
            return
        last_saved.update(at=now, percent=percent, message=message)
        _update_guestbook_progress(movie, percent, message)

    slug = event.slug or event.pk
    previous_names = {
        "final_file": movie.final_file.name if movie.final_file else "",
        "light_file": movie.light_file.name if movie.light_file else "",
    }
    try:
        with tempfile.TemporaryDirectory(prefix="memora_guestbook_out_") as out_dir:
            output_path = Path(out_dir) / f"livre-dor-{slug}.mp4"
            light_path = Path(out_dir) / f"livre-dor-{slug}-leger.mp4"
            result = render_guestbook_montage(
                event, messages, output_path, light_output_path=light_path, progress_callback=_report
            )

            _update_guestbook_progress(movie, 97, "Enregistrement du montage final.")
            movie.final_size = output_path.stat().st_size
            with open(output_path, "rb") as rendered:
                movie.final_file.save(output_path.name, File(rendered), save=False)
            if result.light_path:
                movie.light_size = result.light_path.stat().st_size
                with open(result.light_path, "rb") as rendered:
                    movie.light_file.save(result.light_path.name, File(rendered), save=False)
            else:
                movie.light_file = None
                movie.light_size = None
    except Exception as exc:  # rendu / materialisation / storage
        logger.exception("Guestbook montage failed movie=%s event=%s", movie.pk, event.pk)
        movie.status = GuestBookMovie.Status.FAILED
        movie.error_message = str(exc)[:2000]
        movie.save(update_fields=["status", "error_message", "updated_at"])
        return movie

    movie.status = GuestBookMovie.Status.COMPLETED
    movie.render_provider = "remotion+ffmpeg"
    movie.message_count = len(messages)
    movie.duration = timezone.timedelta(seconds=round(result.duration_seconds))
    movie.completed_at = timezone.now()
    movie.progress_percent = 100
    movie.progress_message = "Montage terminé."
    movie.save(
        update_fields=[
            "status",
            "final_file",
            "final_size",
            "light_file",
            "light_size",
            "render_provider",
            "message_count",
            "duration",
            "completed_at",
            "progress_percent",
            "progress_message",
            "updated_at",
        ]
    )
    _delete_previous_files(movie, previous_names)
    logger.info("Guestbook montage completed movie=%s event=%s messages=%s", movie.pk, event.pk, len(messages))

    # Rattrapage : des messages ont pu etre enregistres pendant le rendu (le montage part des messages
    # presents au demarrage). Sauf si un agent enregistre encore, sa propre fin de service relancera.
    from guestbook.services import has_open_shifts

    if event.guestbook_messages.count() > len(messages) and not has_open_shifts(event):
        movie.status = GuestBookMovie.Status.PENDING
        movie.trigger = "catch_up"
        movie.save(update_fields=["status", "trigger", "updated_at"])
        logger.info("Guestbook montage re-queued (messages added during render) movie=%s event=%s", movie.pk, event.pk)
    return movie
