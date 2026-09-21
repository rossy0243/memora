from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import (
    PasswordChangeView,
    PasswordResetCompleteView,
    PasswordResetConfirmView,
    PasswordResetDoneView,
    PasswordResetView,
    LoginView,
)
from django.http import Http404, HttpResponseRedirect, StreamingHttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.decorators.http import require_POST

from core import throttle
from core.models import SiteConfiguration

from .export import account_export_filename, iter_account_export_zip_chunks
from .forms import AmbassadorApplicationForm, OrganizerSignupForm
from .models import AmbassadorApplication, OrganizerProfile, PayoutRequest
from .services import request_payout


class RoleAwareLoginView(LoginView):
    """Envoie chaque compte vers son espace : agent Memora ou dashboard organisateur.

    Un `next` explicite (lien partagé, redirection apres @login_required) garde
    toujours la priorite sur ce routage automatique.
    """

    template_name = "accounts/login.html"

    def form_invalid(self, form):
        # Tentatives repetees : on le dit clairement (la protection elle-meme est dans
        # core.throttle.ThrottledModelBackend, qui couvre aussi /admin/).
        until = throttle.locked_until(self.request, self.request.POST.get("username", ""))
        if until:
            minutes = max(int((until - timezone.now()).total_seconds() // 60) + 1, 1)
            form.add_error(None, f"Trop de tentatives échouées. Réessayez dans {minutes} min.")
        return super().form_invalid(form)

    def get_default_redirect_url(self):
        if hasattr(self.request.user, "agent_profile"):
            return reverse_lazy("guestbook:agent_home")
        return super().get_default_redirect_url()


def signup(request):
    if request.user.is_authenticated:
        return redirect("dashboard:home")

    if request.method == "POST":
        form = OrganizerSignupForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect("dashboard:home")
    else:
        initial = {}
        referral_code = (request.GET.get("parrain") or "").strip().upper()
        if referral_code:
            initial["referral_code"] = referral_code
        form = OrganizerSignupForm(initial=initial)

    return render(request, "accounts/signup.html", {"form": form})


@login_required
@require_POST
def request_payout_view(request):
    """Demande de retrait des gains disponibles (ambassadeurs uniquement)."""
    profile = OrganizerProfile.for_user(request.user)
    if not profile.is_ambassador:
        raise Http404

    method = request.POST.get("method") or PayoutRequest.Method.MOBILE_MONEY
    details = (request.POST.get("payout_details") or "").strip()

    if not details:
        messages.error(request, "Indiquez où vous souhaitez recevoir le versement.")
        return redirect("dashboard:home")
    if method not in PayoutRequest.Method.values:
        messages.error(request, "Mode de versement invalide.")
        return redirect("dashboard:home")

    try:
        payout = request_payout(request.user, method, details)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("dashboard:home")

    messages.success(
        request,
        f"Demande de retrait de {payout.formatted_amount} enregistrée. "
        "Memora la traite sous quelques jours ouvrés.",
    )
    return redirect("dashboard:home")


@login_required
def export_my_data(request):
    """Export RGPD : toutes les donnees du compte connecte, en une archive ZIP."""
    response = StreamingHttpResponse(
        iter_account_export_zip_chunks(request.user),
        content_type="application/zip",
    )
    response["Content-Disposition"] = (
        f'attachment; filename="{account_export_filename(request.user)}"'
    )
    return response


def password_help(request):
    """Page « mot de passe oublié ».

    Point d'entree unique de la recuperation de compte : propose le lien de
    reinitialisation par e-mail (accounts:password_reset), et garde le contact
    humain (e-mail ou WhatsApp regle en admin) en secours — utile tant qu'aucun
    service d'envoi reel n'est configure, ou si l'organisateur n'a plus acces a
    sa boite mail.
    """
    configuration = SiteConfiguration.current()
    return render(
        request,
        "accounts/password_help.html",
        {
            "support_email": configuration.effective_support_email,
            "whatsapp_link": configuration.whatsapp_link,
            "whatsapp_display": configuration.support_whatsapp,
            "has_support_contact": configuration.has_support_contact,
        },
    )


class AccountPasswordChangeView(LoginRequiredMixin, PasswordChangeView):
    """Changement de mot de passe depuis le compte : organisateurs comme agents.

    Exige l'ancien mot de passe (le formulaire Django le fait) : une session
    laissee ouverte sur un poste partage ne suffit pas a prendre le compte. La
    session reste ouverte apres le changement (update_session_auth_hash).
    """

    template_name = "accounts/password_change.html"

    def get_success_url(self):
        if hasattr(self.request.user, "agent_profile"):
            return reverse("guestbook:agent_home")
        return reverse("dashboard:home")

    def form_valid(self, form):
        messages.success(self.request, "Votre mot de passe a bien été modifié.")
        return super().form_valid(form)


class OrganizerPasswordResetView(PasswordResetView):
    template_name = "accounts/password_reset_form.html"
    email_template_name = "accounts/password_reset_email.txt"
    subject_template_name = "accounts/password_reset_subject.txt"
    from_email = settings.DEFAULT_FROM_EMAIL
    success_url = reverse_lazy("accounts:password_reset_done")

    def form_valid(self, form):
        # Rafale de demandes (e-mail bombing) : on repond comme si tout allait bien, sans rien envoyer
        # ni reveler quoi que ce soit.
        if not throttle.allow_reset_request(self.request, form.cleaned_data["email"]):
            return HttpResponseRedirect(self.get_success_url())
        return super().form_valid(form)


class OrganizerPasswordResetDoneView(PasswordResetDoneView):
    template_name = "accounts/password_reset_done.html"


class OrganizerPasswordResetConfirmView(PasswordResetConfirmView):
    template_name = "accounts/password_reset_confirm.html"
    success_url = reverse_lazy("accounts:password_reset_complete")


class OrganizerPasswordResetCompleteView(PasswordResetCompleteView):
    template_name = "accounts/password_reset_complete.html"


@login_required
def become_ambassador(request):
    """Candidature au statut Ambassadeur : numero de piece d'identite + scan.

    Volontairement absent de l'inscription (qui doit rester simple) : ce n'est
    demande qu'aux organisateurs qui visent le statut Ambassadeur. Le fichier
    est analyse (metadonnees, traces de retouche) a la soumission ; la decision
    d'octroi reste toujours humaine (voir AmbassadorApplication.approve).
    """
    profile = OrganizerProfile.for_user(request.user)
    if profile.is_ambassador:
        messages.info(request, "Vous êtes déjà ambassadeur Memora.")
        return redirect("dashboard:home")

    latest_application = (
        AmbassadorApplication.objects.filter(organizer=request.user).order_by("-submitted_at").first()
    )
    if latest_application and latest_application.status == AmbassadorApplication.Status.PENDING:
        return render(
            request,
            "accounts/become_ambassador.html",
            {"application": latest_application},
        )

    if request.method == "POST":
        form = AmbassadorApplicationForm(request.POST, request.FILES)
        if form.is_valid():
            application = form.save(commit=False)
            application.organizer = request.user
            application.save()
            messages.success(
                request,
                "Votre candidature a bien été envoyée. Memora l'examine sous quelques jours.",
            )
            return redirect("dashboard:home")
    else:
        form = AmbassadorApplicationForm()

    return render(
        request,
        "accounts/become_ambassador.html",
        {"form": form, "application": latest_application},
    )
