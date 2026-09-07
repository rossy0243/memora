"""Sondage de la duree d'une video via ffprobe, partage par tous les formulaires
qui recoivent des videos (invite, livre d'or agent).
"""

from pathlib import Path
import json
import shutil
import subprocess
import tempfile


class VideoDurationUnavailable(Exception):
    """ffprobe n'a pas pu determiner la duree de la video."""


def probe_video_duration(media_file, ffprobe_binary, timeout=15):
    if shutil.which(ffprobe_binary) is None and not Path(ffprobe_binary).exists():
        raise VideoDurationUnavailable

    original_position = media_file.tell() if hasattr(media_file, "tell") else None
    temporary_path = None

    try:
        if hasattr(media_file, "seek"):
            media_file.seek(0)

        suffix = Path(media_file.name).suffix.lower() or ".video"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temporary_file:
            temporary_path = Path(temporary_file.name)
            for chunk in media_file.chunks():
                temporary_file.write(chunk)

        commands = [
            [
                ffprobe_binary,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(temporary_path),
            ],
            [
                ffprobe_binary,
                "-v",
                "error",
                "-analyzeduration",
                "100M",
                "-probesize",
                "100M",
                "-show_entries",
                "format=duration:stream=duration",
                "-of",
                "json",
                str(temporary_path),
            ],
        ]

        for command in commands:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout,
            )
            if result.returncode == 0:
                duration = _duration_from_ffprobe_payload(result.stdout)
                if duration is not None:
                    return duration

        raise VideoDurationUnavailable
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, subprocess.TimeoutExpired):
        raise VideoDurationUnavailable
    finally:
        if hasattr(media_file, "seek"):
            media_file.seek(original_position or 0)
        if temporary_path:
            temporary_path.unlink(missing_ok=True)


def _duration_from_ffprobe_payload(payload):
    data = json.loads(payload or "{}")
    format_duration = data.get("format", {}).get("duration")
    if format_duration not in (None, "N/A"):
        duration = float(format_duration)
        if duration > 0:
            return duration

    for stream in data.get("streams", []):
        stream_duration = stream.get("duration")
        if stream_duration not in (None, "N/A"):
            duration = float(stream_duration)
            if duration > 0:
                return duration

    return None
