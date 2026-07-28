from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from core.models import SiteConfiguration

from .forms import OrganizerSignupForm
from .models import OrganizerProfile, PayoutRequest
from .services import request_payout


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


def password_help(request):
    """Page « mot de passe oublié ».

    Memora n'envoie pas de lien de réinitialisation automatique : la remise à
    zéro passe par un contact humain (e-mail ou WhatsApp), dont les coordonnées
    sont réglées en admin. On évite ainsi de promettre un e-mail que la
    configuration d'envoi ne garantit pas encore.
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
