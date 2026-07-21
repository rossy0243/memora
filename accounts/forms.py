from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import get_user_model

from .models import OrganizerProfile


class OrganizerSignupForm(UserCreationForm):
    email = forms.EmailField(required=True)
    referral_code = forms.CharField(
        required=False,
        max_length=12,
        label="Code de parrainage (optionnel)",
        help_text="Si un organisateur Memora vous a invité, entrez son code.",
    )

    class Meta:
        model = get_user_model()
        fields = ("username", "email")

    def clean_referral_code(self):
        code = (self.cleaned_data.get("referral_code") or "").strip().upper()
        if not code:
            return ""
        referrer_profile = OrganizerProfile.objects.filter(referral_code=code).first()
        if not referrer_profile:
            raise forms.ValidationError("Ce code de parrainage est inconnu.")
        self._referrer = referrer_profile.user
        return code

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        if commit:
            user.save()
            referrer = getattr(self, "_referrer", None)
            if referrer:
                profile = OrganizerProfile.for_user(user)
                profile.referred_by = referrer
                profile.save(update_fields=["referred_by", "updated_at"])
        return user
