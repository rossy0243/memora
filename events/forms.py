from io import BytesIO
from pathlib import Path

from django import forms
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image, UnidentifiedImageError

from .models import Event, EventType


class EventForm(forms.ModelForm):
    class Meta:
        model = Event
        fields = (
            "title",
            "couple_name",
            "event_type",
            "event_date",
            "location",
            "cover_image",
            "welcome_message",
            "guest_access_code",
            "is_active",
        )
        widgets = {
            "event_date": forms.DateInput(attrs={"type": "date"}),
            "welcome_message": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["event_type"].queryset = EventType.objects.filter(is_active=True)
        placeholders = {
            "title": "Mariage de Camille & Noe",
            "couple_name": "Camille & Noe",
            "location": "Domaine des roses, Bordeaux",
            "welcome_message": "Merci de partager vos photos et videos de cette journee.",
            "guest_access_code": "AMOUR2026",
        }
        for name, field in self.fields.items():
            field.widget.attrs.setdefault("class", "form-control")
            if name in placeholders:
                field.widget.attrs.setdefault("placeholder", placeholders[name])
        self.fields["cover_image"].help_text = "Image JPG, PNG ou WEBP. 8 Mo maximum."
        self.fields["cover_image"].widget.attrs.update(
            {
                "accept": ".jpg,.jpeg,.png,.webp,image/jpeg,image/png,image/webp",
            }
        )

    def clean_cover_image(self):
        cover_image = self.cleaned_data.get("cover_image")
        if not cover_image:
            return cover_image

        if cover_image.size > settings.MEMORA_MAX_COVER_IMAGE_SIZE:
            raise forms.ValidationError("Cette image est trop lourde. Choisissez une image de 8 Mo maximum.")

        content_type = (getattr(cover_image, "content_type", "") or "").split(";")[0].lower()
        if content_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise forms.ValidationError("Ce format d'image n'est pas accepte.")

        try:
            image = Image.open(cover_image)
            image.verify()
        except (UnidentifiedImageError, OSError):
            raise forms.ValidationError("Cette image ne peut pas etre lue.")

        cover_image.seek(0)
        image = Image.open(cover_image)
        image = image.convert("RGB")
        image.thumbnail(
            (
                settings.MEMORA_COVER_IMAGE_MAX_WIDTH,
                settings.MEMORA_COVER_IMAGE_MAX_HEIGHT,
            ),
            Image.Resampling.LANCZOS,
        )

        output = BytesIO()
        image.save(output, format="JPEG", quality=84, optimize=True)
        output.seek(0)

        original_name = Path(cover_image.name).stem or "couverture"
        return SimpleUploadedFile(
            f"{original_name}.jpg",
            output.read(),
            content_type="image/jpeg",
        )
