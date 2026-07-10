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
        raise forms.ValidationError("La duree de cette video ne peut pas etre verifiee.")

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

        result = subprocess.run(
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
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
        if result.returncode != 0:
            raise forms.ValidationError("La duree de cette video ne peut pas etre verifiee.")

        payload = json.loads(result.stdout or "{}")
        return float(payload["format"]["duration"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, subprocess.TimeoutExpired):
        raise forms.ValidationError("La duree de cette video ne peut pas etre verifiee.")
    finally:
        if hasattr(media_file, "seek"):
            media_file.seek(original_position or 0)
        if temporary_path:
            temporary_path.unlink(missing_ok=True)


class GuestUploadForm(forms.ModelForm):
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
        self.fields["category"].empty_label = "Selectionner un moment"
        self.fields["category"].required = True
        self.fields["category"].widget.attrs.update(
            {
                "class": "moment-select",
                "required": "required",
            }
        )

    def clean_media_file(self):
        media_file = self.cleaned_data["media_file"]
        extension = Path(media_file.name).suffix.lower().lstrip(".")

        if extension not in settings.MEMORA_ALLOWED_UPLOAD_EXTENSIONS:
            raise forms.ValidationError("Ce format n'est pas accepte.")

        allowed_content_types = settings.MEMORA_ALLOWED_UPLOAD_CONTENT_TYPES.get(extension, [])
        content_type = (media_file.content_type or "").split(";")[0].strip().lower()
        if content_type not in allowed_content_types:
            raise forms.ValidationError("Ce format n'est pas accepte.")

        if media_file.size > settings.MEMORA_MAX_UPLOAD_SIZE:
            raise forms.ValidationError("Cette video est trop lourde.")

        if extension in settings.MEMORA_VIDEO_EXTENSIONS:
            duration_seconds = _probe_video_duration(media_file)
            if duration_seconds > settings.MEMORA_MAX_VIDEO_UPLOAD_DURATION_SECONDS:
                raise forms.ValidationError("Cette video depasse 10 secondes.")
            self.media_duration = timedelta(seconds=duration_seconds)

        return media_file

    @staticmethod
    def get_media_type(filename):
        extension = Path(filename).suffix.lower().lstrip(".")
        if extension in settings.MEMORA_IMAGE_EXTENSIONS:
            return GuestUpload.MediaType.IMAGE
        if extension in settings.MEMORA_VIDEO_EXTENSIONS:
            return GuestUpload.MediaType.VIDEO
        return ""
