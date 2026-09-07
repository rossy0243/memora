from datetime import timedelta
from pathlib import Path

from django import forms
from django.conf import settings

from core.video import VideoDurationUnavailable, probe_video_duration

from .models import GuestBookMessage


def _probe_video_duration(media_file):
    try:
        return probe_video_duration(media_file, settings.MEMORA_FFPROBE_BINARY)
    except VideoDurationUnavailable:
        raise forms.ValidationError("La durée de ce message ne peut pas être vérifiée.")


class GuestBookMessageForm(forms.ModelForm):
    client_duration_seconds = forms.FloatField(
        required=False,
        min_value=0,
        widget=forms.HiddenInput(attrs={"id": "client-duration-seconds"}),
    )

    class Meta:
        model = GuestBookMessage
        fields = ("guest_name", "media_file")
        widgets = {
            "guest_name": forms.TextInput(attrs={"placeholder": "De la part de... (facultatif)"}),
            "media_file": forms.FileInput(
                attrs={
                    "accept": ".mp4,.mov,.webm,video/*",
                    "class": "memora-camera-file-input",
                }
            ),
        }
        labels = {
            "guest_name": "De la part de",
            "media_file": "Message video",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["guest_name"].required = False
        self.media_duration = None

    def clean_media_file(self):
        media_file = self.cleaned_data["media_file"]
        extension = Path(media_file.name).suffix.lower().lstrip(".")

        if extension not in settings.MEMORA_VIDEO_EXTENSIONS:
            raise forms.ValidationError("Ce format n'est pas accepté.")

        allowed_content_types = settings.MEMORA_ALLOWED_UPLOAD_CONTENT_TYPES.get(extension, [])
        content_type = (media_file.content_type or "").split(";")[0].strip().lower()
        if content_type not in allowed_content_types:
            raise forms.ValidationError("Ce format n'est pas accepté.")

        if media_file.size > settings.MEMORA_MAX_UPLOAD_SIZE:
            raise forms.ValidationError("Ce message est trop lourd.")

        duration_seconds = self._client_duration_seconds()
        try:
            duration_seconds = _probe_video_duration(media_file)
        except forms.ValidationError:
            if not duration_seconds or media_file.size > settings.MEMORA_CLIENT_DURATION_FALLBACK_MAX_SIZE:
                raise forms.ValidationError("La durée de ce message ne peut pas être vérifiée.")

        max_seconds = settings.MEMORA_GUESTBOOK_MAX_VIDEO_DURATION_SECONDS
        if duration_seconds > max_seconds:
            raise forms.ValidationError(f"Ce message dépasse {max_seconds} secondes.")
        self.media_duration = timedelta(seconds=duration_seconds)

        return media_file

    def _client_duration_seconds(self):
        raw_duration = self.data.get(self.add_prefix("client_duration_seconds")) if self.is_bound else None
        try:
            duration_seconds = float(raw_duration)
        except (TypeError, ValueError):
            return None
        return duration_seconds if duration_seconds > 0 else None
