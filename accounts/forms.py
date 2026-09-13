import warnings

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import get_user_model
from PIL import Image

from .identity_check import analyze_identity_document
from .models import AmbassadorApplication, OrganizerProfile


class OrganizerSignupForm(UserCreationForm):
    email = forms.EmailField(
        required=True,
        label="Adresse e-mail",
        help_text="Elle sert à vous prévenir quand votre film souvenir est prêt, et à récupérer votre compte en cas de mot de passe oublié.",
    )
    referral_code = forms.CharField(
        required=False,
        max_length=12,
        label="Code de parrainage (optionnel)",
        help_text="Si un organisateur Memora vous a invité, entrez son code.",
    )
    accept_terms = forms.BooleanField(
        required=True,
        label="J'ai lu et j'accepte les CGU",
        error_messages={"required": "Vous devez accepter les CGU pour créer un compte."},
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
        from django.utils import timezone

        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        if commit:
            user.save()
            profile = OrganizerProfile.for_user(user)
            if self.cleaned_data.get("accept_terms"):
                profile.terms_accepted_at = timezone.now()
                profile.save(update_fields=["terms_accepted_at", "updated_at"])
            referrer = getattr(self, "_referrer", None)
            if referrer:
                # attach_referrer demarre aussi le compteur d'affiliation.
                profile.attach_referrer(referrer)
        return user


_MAX_ID_DOCUMENT_SIZE = 10 * 1024 * 1024  # 10 Mo : large pour un scan net, pas pour un exploit.
_ALLOWED_ID_DOCUMENT_FORMATS = {"jpeg", "png"}


class AmbassadorApplicationForm(forms.ModelForm):
    class Meta:
        model = AmbassadorApplication
        fields = ("id_document_number", "id_document_file")
        labels = {
            "id_document_number": "Numéro de la pièce d'identité",
            "id_document_file": "Photo scannée de la pièce d'identité",
        }
        help_texts = {
            "id_document_number": "Carte d'identité, passeport ou permis de conduire.",
            "id_document_file": "Format JPG ou PNG, document entier et lisible.",
        }

    def clean_id_document_file(self):
        """Valide le fichier PUIS lance l'analyse heuristique (accounts.identity_check)
        sur les octets bruts, avant toute transformation — l'EXIF ne survivrait
        pas a un re-encodage."""
        uploaded = self.cleaned_data["id_document_file"]

        if uploaded.size > _MAX_ID_DOCUMENT_SIZE:
            raise forms.ValidationError("Le fichier dépasse la taille maximale (10 Mo).")

        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                image = Image.open(uploaded)
                image.load()
                detected_format = (image.format or "").lower()
        except forms.ValidationError:
            raise
        except Exception as exc:
            raise forms.ValidationError("Ce fichier n'est pas une image valide.") from exc

        if detected_format not in _ALLOWED_ID_DOCUMENT_FORMATS:
            raise forms.ValidationError("Formats acceptés : JPG ou PNG.")

        uploaded.seek(0)
        self._tamper_analysis = analyze_identity_document(uploaded)
        uploaded.seek(0)
        return uploaded

    def save(self, commit=True):
        application = super().save(commit=False)
        analysis = getattr(self, "_tamper_analysis", {"risk_score": 0, "flags": []})
        application.tamper_risk_score = analysis["risk_score"]
        application.tamper_flags = analysis["flags"]
        if commit:
            application.save()
        return application
