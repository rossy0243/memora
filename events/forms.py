from django import forms

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
            "is_active",
            "media_retention_days",
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
        }
        for name, field in self.fields.items():
            field.widget.attrs.setdefault("class", "form-control")
            if name in placeholders:
                field.widget.attrs.setdefault("placeholder", placeholders[name])
