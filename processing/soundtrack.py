from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist

from .analysis import get_analysis_score


SUPPORTED_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}

# Tempo mesure hors ligne (enveloppe d'energie + autocorrelation) : (BPM, 1er temps en s).
# Certaines valeurs sont a l'octave superieure du tempo ressenti ; sans importance,
# un multiple exact de l'intervalle reste cale sur la grille musicale.
TRACK_TEMPOS = {
    "cinematic_emotional_emotional_piano_loop.mp3": (154.2, 0.01),
    "elegant_warm_a_new_town.mp3": (176.9, 0.04),
    "joyful_party_party_sector.mp3": (120.3, 0.03),
    "romantic_cinematic_synthwave_421k.mp3": (85.9, 1.25),
    "warm_lounge_one_step_at_a_time.mp3": (80.2, 0.41),
}

DEFAULT_BPM = 100.0


@dataclass(frozen=True)
class SoundtrackChoice:
    mood: str
    track_path: Path | None
    reason: str
    bpm: float = 0.0
    first_beat_offset: float = 0.0

    @property
    def track_name(self):
        return self.track_path.name if self.track_path else ""

    @property
    def beat_interval(self):
        """Duree d'un temps, en secondes. 0 si le tempo est inconnu."""
        return 60.0 / self.bpm if self.bpm else 0.0


def get_track_tempo(track_path):
    """(BPM, decalage du 1er temps) pour une piste connue, sinon (0, 0)."""
    if not track_path:
        return 0.0, 0.0
    return TRACK_TEMPOS.get(Path(track_path).name, (0.0, 0.0))


def choose_movie_soundtrack(event, uploads):
    mood = choose_music_mood(event, uploads)
    track_path = find_track_for_mood(mood)
    reason = "Bibliotheque musicale non configuree"
    if track_path:
        reason = f"Piste choisie pour le mood {mood}"
    bpm, first_beat_offset = get_track_tempo(track_path)
    return SoundtrackChoice(
        mood=mood,
        track_path=track_path,
        reason=reason,
        bpm=bpm,
        first_beat_offset=first_beat_offset,
    )


def choose_music_mood(event, uploads):
    category_codes = [upload.category.code for upload in uploads if upload.category_id]
    tags = []
    for upload in uploads:
        try:
            tags.extend(upload.analysis.tags)
        except ObjectDoesNotExist:
            continue

    if _contains_any(category_codes, {"dancefloor", "funny"}) or "energie" in tags:
        return "joyful_party"
    if _contains_any(category_codes, {"speech", "emotional"}) or "voix" in tags:
        return "cinematic_emotional"
    if _contains_any(category_codes, {"ceremony", "cake"}):
        return "romantic_cinematic"
    if _contains_any(category_codes, {"cocktail", "reception"}):
        return "warm_lounge"
    if getattr(event.event_type, "code", "") == "wedding":
        return "romantic_cinematic"
    return "elegant_warm"


def find_track_for_mood(mood):
    music_dir = Path(settings.MEMORA_MOVIE_MUSIC_DIR)
    if not music_dir.exists():
        return None

    tracks = sorted(
        path
        for path in music_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_AUDIO_EXTENSIONS
    )
    if not tracks:
        return None

    normalized_mood = mood.lower().replace("-", "_").replace(" ", "_")
    mood_tokens = set(normalized_mood.split("_"))
    normalized_tracks = [
        (track, track.stem.lower().replace("-", "_").replace(" ", "_"))
        for track in tracks
    ]

    for track, normalized_name in normalized_tracks:
        if normalized_name.startswith(normalized_mood) or normalized_mood in normalized_name:
            return track

    for track, normalized_name in normalized_tracks:
        if mood_tokens.issubset(set(normalized_name.split("_"))):
            return track

    for track in tracks:
        normalized_name = track.stem.lower().replace("-", "_").replace(" ", "_")
        if any(token in normalized_name for token in mood_tokens):
            return track

    return tracks[0]


def build_edit_decision_data(event, uploads, soundtrack):
    cursor = 0
    clips = []
    for position, upload in enumerate(uploads, start=1):
        duration = _clip_duration(upload)
        clips.append(
            {
                "position": position,
                "upload_id": upload.pk,
                "filename": upload.original_filename,
                "category": upload.category.code,
                "media_type": upload.media_type,
                "score": get_analysis_score(upload),
                "start": cursor,
                "end": cursor + duration,
                "duration": duration,
                "keep_original_voice": upload.media_type == upload.MediaType.VIDEO,
            }
        )
        cursor += duration

    return {
        "event_id": event.pk,
        "event_title": event.title,
        "max_duration_seconds": settings.MEMORA_MOVIE_MAX_DURATION_SECONDS,
        "render_style": "premium_event_memory",
        "soundtrack": {
            "mood": soundtrack.mood,
            "track": soundtrack.track_name,
            "reason": soundtrack.reason,
            "music_volume": settings.MEMORA_MOVIE_MUSIC_VOLUME,
            "voice_volume": settings.MEMORA_MOVIE_VOICE_VOLUME,
            "ducked_music_volume": settings.MEMORA_MOVIE_DUCKED_MUSIC_VOLUME,
        },
        "audio_strategy": {
            "keep_guest_voice": True,
            "duck_music_when_voice_is_present": True,
            "raise_music_between_voice_moments": True,
        },
        "clips": clips,
    }


def _contains_any(values, expected):
    return bool(set(values) & expected)


def _clip_duration(upload):
    if upload.media_type == upload.MediaType.IMAGE:
        return settings.MEMORA_MOVIE_IMAGE_DURATION_SECONDS
    if upload.duration:
        return min(int(upload.duration.total_seconds()), settings.MEMORA_MOVIE_VIDEO_MAX_SECONDS)
    return settings.MEMORA_MOVIE_VIDEO_MAX_SECONDS
