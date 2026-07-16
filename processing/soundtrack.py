from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist

from .analysis import get_analysis_score


SUPPORTED_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}


@dataclass(frozen=True)
class SoundtrackChoice:
    mood: str
    track_path: Path | None
    reason: str

    @property
    def track_name(self):
        return self.track_path.name if self.track_path else ""


def choose_movie_soundtrack(event, uploads):
    mood = choose_music_mood(event, uploads)
    track_path = find_track_for_mood(mood)
    reason = "Bibliotheque musicale non configuree"
    if track_path:
        reason = f"Piste choisie pour le mood {mood}"
    return SoundtrackChoice(mood=mood, track_path=track_path, reason=reason)


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
