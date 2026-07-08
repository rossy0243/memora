from pathlib import Path

from django import forms
from django.conf import settings

from .models import GuestUpload, UploadCategory


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
            "category": forms.RadioSelect,
        }
        labels = {
            "media_file": "Photo ou video",
            "category": "Moment",
        }

    def __init__(self, *args, event=None, **kwargs):
        super().__init__(*args, **kwargs)
        queryset = UploadCategory.objects.filter(is_active=True)
        if event is not None:
            queryset = queryset.filter(event=event)
        self.fields["category"].queryset = queryset
        self.fields["category"].empty_label = None

    def clean_media_file(self):
        media_file = self.cleaned_data["media_file"]
        extension = Path(media_file.name).suffix.lower().lstrip(".")

        if extension not in settings.MEMORA_ALLOWED_UPLOAD_EXTENSIONS:
            raise forms.ValidationError("Ce format n'est pas accepte.")

        if media_file.size > settings.MEMORA_MAX_UPLOAD_SIZE:
            raise forms.ValidationError("Cette video est trop lourde.")

        return media_file

    @staticmethod
    def get_media_type(filename):
        extension = Path(filename).suffix.lower().lstrip(".")
        if extension in settings.MEMORA_IMAGE_EXTENSIONS:
            return GuestUpload.MediaType.IMAGE
        if extension in settings.MEMORA_VIDEO_EXTENSIONS:
            return GuestUpload.MediaType.VIDEO
        return ""
