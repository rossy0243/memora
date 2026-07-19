from io import BytesIO
from pathlib import Path

from django import forms
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils.text import slugify
from PIL import Image, UnidentifiedImageError

from uploads.models import MomentTemplate
from uploads.services import (
    get_available_moment_templates,
    get_default_moment_templates_for_event_type,
    get_event_type_moment_suggestions,
    sync_event_upload_categories,
)

from .models import Event, EventType


class MomentMultipleChoiceField(forms.MultipleChoiceField):
    def valid_value(self, value):
        return True


class EventForm(forms.ModelForm):
    custom_event_type_label = forms.CharField(
        required=False,
        max_length=80,
        label="Type d'événement personnalisé",
        help_text="Exemple : baptême, gala, baby shower, soirée de famille.",
    )

    moments = MomentMultipleChoiceField(
        required=False,
        label="Moments proposés aux invités",
        help_text="Recherchez des moments existants ou ajoutez les vôtres. Vos invités les choisiront au moment d'envoyer un souvenir.",
    )

    class Meta:
        model = Event
        fields = (
            "title",
            "couple_name",
            "event_type",
            "custom_event_type_label",
            "moments",
            "event_date",
            "cover_image",
            "welcome_message",
            "guest_access_code",
        )
        widgets = {
            "event_date": forms.DateInput(attrs={"type": "date"}),
            "welcome_message": forms.Textarea(attrs={"rows": 4}),
        }
        labels = {
            "title": "Nom de l'événement",
            "couple_name": "Nom affiché aux invités",
            "event_type": "Type d'événement",
            "event_date": "Date de l'événement",
            "cover_image": "Image de couverture",
            "welcome_message": "Message d'accueil",
            "guest_access_code": "Code invité (optionnel)",
        }
        help_texts = {
            "title": "Nom interne visible dans votre tableau de bord.",
            "couple_name": "Pour un mariage : Camille & Noé. Pour un autre événement : Anniversaire de Lina, Gala Memora...",
            "event_type": "Les moments proposés aux invités s'adaptent au type choisi.",
            "event_date": "Les médias seront conservés 7 jours après cette date.",
            "welcome_message": "Une phrase courte suffit. Elle apparaît sur la page invitée.",
            "guest_access_code": "À utiliser seulement si vous voulez ajouter une sécurité après le QR code.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["event_type"].queryset = EventType.objects.filter(is_active=True)
        self._moment_templates = list(get_available_moment_templates())
        self.fields["moments"].choices = [(str(moment.pk), moment.label) for moment in self._moment_templates]
        placeholders = {
            "title": "Mariage de Camille & Noé, Anniversaire de Lina...",
            "couple_name": "Camille & Noé, Anniversaire de Lina, Gala Memora...",
            "custom_event_type_label": "Soirée de famille",
            "welcome_message": "Merci de partager vos photos et vidéos de cette journée.",
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
        self.fields["event_type"].empty_label = "Choisir un type"
        other_event_type = EventType.objects.filter(code="other", is_active=True).first()
        self.fields["event_type"].widget.attrs.update(
            {
                "data-event-type-select": "true",
                "data-other-event-type-id": str(other_event_type.pk) if other_event_type else "",
            }
        )
        self.fields["custom_event_type_label"].widget.attrs.update(
            {
                "data-custom-event-type": "true",
                "autocomplete": "off",
            }
        )
        self.fields["moments"].widget.attrs.update(
            {
                "data-moment-select": "true",
                "class": "form-control moment-native-select",
            }
        )
        self.moment_suggestions_data = get_event_type_moment_suggestions()
        self._add_existing_custom_moment_choices()
        if self.instance and self.instance.pk:
            self.fields["moments"].initial = self._initial_moment_values_for_event()

    def clean_custom_event_type_label(self):
        return (self.cleaned_data.get("custom_event_type_label") or "").strip()

    def clean(self):
        cleaned_data = super().clean()
        event_type = cleaned_data.get("event_type")
        custom_label = cleaned_data.get("custom_event_type_label")

        if event_type and event_type.code == "other" and not custom_label:
            self.add_error(
                "custom_event_type_label",
                "Indiquez le type d'événement pour éviter un libellé vague.",
            )

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        is_new = instance.pk is None
        event_type = self.cleaned_data.get("event_type")
        custom_label = self.cleaned_data.get("custom_event_type_label")
        moment_values = self.cleaned_data.get("moments") or []
        instance.media_retention_days = Event._meta.get_field("media_retention_days").default
        instance.is_active = True

        if event_type and event_type.code == "other" and custom_label:
            custom_code = slugify(custom_label)[:40] or "evenement"
            base_code = custom_code
            counter = 2
            while EventType.objects.filter(code=custom_code).exclude(label__iexact=custom_label).exists():
                suffix = f"-{counter}"
                custom_code = f"{base_code[: 40 - len(suffix)]}{suffix}"
                counter += 1
            instance.event_type, _ = EventType.objects.get_or_create(
                code=custom_code,
                defaults={
                    "label": custom_label,
                    "sort_order": 90,
                    "is_active": True,
                },
            )

        if commit:
            instance.save()
            self.save_m2m()
            sync_event_upload_categories(
                instance,
                moment_values,
                user=instance.organizer,
                count_all_usage=is_new,
            )
        return instance

    def _add_existing_custom_moment_choices(self):
        existing_values = []
        if self.instance and self.instance.pk:
            existing_values = self._initial_moment_values_for_event()

        known_values = {str(value) for value, _ in self.fields["moments"].choices}
        choices = list(self.fields["moments"].choices)
        for value in existing_values:
            if value in known_values:
                continue
            if value.startswith("new:"):
                choices.append((value, value[4:]))
            else:
                moment = MomentTemplate.objects.filter(pk=value).first()
                if not moment:
                    continue
                choices.append((value, moment.label))
            known_values.add(value)
        self.fields["moments"].choices = choices

    def _initial_moment_values_for_event(self):
        moments_by_code = {moment.code: moment for moment in MomentTemplate.objects.filter(is_active=True)}
        values = []
        for category in self.instance.upload_categories.filter(is_active=True).order_by("sort_order", "label"):
            moment = moments_by_code.get(category.code)
            if moment and moment.status != MomentTemplate.ModerationStatus.REJECTED:
                values.append(str(moment.pk))
            else:
                values.append(f"new:{category.label}")
        return values

    def clean_cover_image(self):
        cover_image = self.cleaned_data.get("cover_image")
        if not cover_image:
            return cover_image

        if cover_image.size > settings.MEMORA_MAX_COVER_IMAGE_SIZE:
            raise forms.ValidationError("Cette image est trop lourde. Choisissez une image de 8 Mo maximum.")

        content_type = (getattr(cover_image, "content_type", "") or "").split(";")[0].lower()
        if content_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise forms.ValidationError("Ce format d'image n'est pas accepté.")

        try:
            image = Image.open(cover_image)
            image.verify()
        except (UnidentifiedImageError, OSError):
            raise forms.ValidationError("Cette image ne peut pas être lue.")

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
