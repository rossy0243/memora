from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import get_user_model

from .models import OrganizerProfile


class OrganizerSignupForm(UserCreationForm):
    email = forms.EmailField(
        required=True,
        label="Adresse e-mail",
        help_text="Elle sert à vous prévenir quand votre film souvenir est prêt.",
    )
    referral_code = forms.CharField(
        required=False,
        max_length=12,
        label="Code de parrainage (optionnel)",
        help_text="Si un organisateur Memora vous a invité, entrez son code.",
    )

    class Meta:
        model = get_user_model()
        fields = ("username", "email")

    def clean_email(self):
        """Un e-mail = un compte.

        Comparaison insensible a la casse et e-mail normalise en minuscules :
        « Foo@gmail.com » et « foo@gmail.com » sont la meme boite aux lettres chez
        tous les fournisseurs courants, et laisser passer les deux ouvrirait un
        second compte — donc une seconde remise de bienvenue.
        """
        email = (self.cleaned_data.get("email") or "").strip().lower()
        if not email:
            return email
        if get_user_model().objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(
                "Un compte existe déjà avec cette adresse e-mail. "
                "Connectez-vous, ou utilisez une autre adresse."
            )
        return email

    def clean_username(self):
        """Nom d'utilisateur unique, insensible a la casse.

        `AbstractUser.username` est deja unique, mais la contrainte est sensible
        a la casse : « Marie » et « marie » cohabiteraient et preteraient a
        confusion a la connexion.
        """
        username = (self.cleaned_data.get("username") or "").strip()
        if username and get_user_model().objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("Ce nom d'utilisateur est déjà pris.")
        return username

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
                # attach_referrer demarre aussi le compteur d'affiliation.
                OrganizerProfile.for_user(user).attach_referrer(referrer)
        return user
