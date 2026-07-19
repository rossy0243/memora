from datetime import timedelta
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from django import forms
from django.conf import settings

from .models import GuestUpload, UploadCategory


def _probe_video_duration(media_file):
    ffprobe_binary = settings.MEMORA_FFPROBE_BINARY
    if shutil.which(ffprobe_binary) is None and not Path(ffprobe_binary).exists():
        raise forms.ValidationError("La durée de cette vidéo ne peut pas être vérifiée.")

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
                timeout=15,
            )
            if result.returncode == 0:
                duration = _duration_from_ffprobe_payload(result.stdout)
                if duration is not None:
                    return duration

        raise forms.ValidationError("La durée de cette vidéo ne peut pas être vérifiée.")
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, subprocess.TimeoutExpired):
        raise forms.ValidationError("La durée de cette vidéo ne peut pas être vérifiée.")
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


class GuestUploadForm(forms.ModelForm):
    client_duration_seconds = forms.FloatField(
        required=False,
        min_value=0,
        widget=forms.HiddenInput(attrs={"id": "client-duration-seconds"}),
    )

    class Meta:
        model = GuestUpload
        fields = ("media_file", "category")
        widgets = {
            "media_file": forms.FileInput(
                attrs={
                    "accept": ".jpg,.jpeg,.png,.webp,.mp4,.mov,.webm,image/*,video/*",
                    "capture": "environment",
                }
            ),
            "category": forms.Select,
        }
        labels = {
            "media_file": "Photo ou video",
            "category": "Moment obligatoire",
        }

    def __init__(self, *args, event=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.media_duration = None
        queryset = UploadCategory.objects.filter(is_active=True)
        if event is not None:
            queryset = queryset.filter(event=event)
        self.fields["category"].queryset = queryset
        self.fields["category"].label_from_instance = lambda category: category.label
        self.fields["category"].empty_label = "Moment"
        self.fields["category"].required = True
        self.fields["category"].widget.attrs.update(
            {
                "class": "moment-select",
                "required": "required",
                "aria-label": "Moment obligatoire",
            }
        )

    def clean_media_file(self):
        media_file = self.cleaned_data["media_file"]
        extension = Path(media_file.name).suffix.lower().lstrip(".")

        if extension not in settings.MEMORA_ALLOWED_UPLOAD_EXTENSIONS:
            raise forms.ValidationError("Ce format n'est pas accepté.")

        allowed_content_types = settings.MEMORA_ALLOWED_UPLOAD_CONTENT_TYPES.get(extension, [])
        content_type = (media_file.content_type or "").split(";")[0].strip().lower()
        if content_type not in allowed_content_types:
            raise forms.ValidationError("Ce format n'est pas accepté.")

        if media_file.size > settings.MEMORA_MAX_UPLOAD_SIZE:
            raise forms.ValidationError("Cette vidéo est trop lourde.")

        if extension in settings.MEMORA_VIDEO_EXTENSIONS:
            duration_seconds = self._client_duration_seconds()
            try:
                duration_seconds = _probe_video_duration(media_file)
            except forms.ValidationError:
                if not duration_seconds or media_file.size > settings.MEMORA_CLIENT_DURATION_FALLBACK_MAX_SIZE:
                    raise forms.ValidationError("La durée de cette vidéo ne peut pas être vérifiée.")

            if duration_seconds > settings.MEMORA_MAX_VIDEO_UPLOAD_DURATION_SECONDS:
                raise forms.ValidationError("Cette vidéo dépasse 10 secondes.")
            self.media_duration = timedelta(seconds=duration_seconds)

        return media_file

    def _client_duration_seconds(self):
        raw_duration = None
        if self.is_bound:
            raw_duration = self.data.get(self.add_prefix("client_duration_seconds"))
        else:
            raw_duration = self.cleaned_data.get("client_duration_seconds")

        try:
            duration_seconds = float(raw_duration)
        except (TypeError, ValueError):
            return None

        if duration_seconds <= 0:
            return None

        return duration_seconds

    @staticmethod
    def get_media_type(filename):
        extension = Path(filename).suffix.lower().lstrip(".")
        if extension in settings.MEMORA_IMAGE_EXTENSIONS:
            return GuestUpload.MediaType.IMAGE
        if extension in settings.MEMORA_VIDEO_EXTENSIONS:
            return GuestUpload.MediaType.VIDEO
        return ""
