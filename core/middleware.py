"""Middlewares transverses de Memora."""
import time
from urllib.parse import urlencode, urlsplit

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.http import HttpResponse, HttpResponsePermanentRedirect
from django.shortcuts import redirect
from django.urls import reverse

LAST_ACTIVITY_KEY = "memora_last_activity"


class CanonicalHostRedirectMiddleware:
    """Renvoie les anciennes adresses `*.onrender.com` vers le domaine officiel.

    Les liens deja partages (QR codes imprimes, e-mails, favoris) pointent vers
    l'adresse Render : ils continuent de marcher, en arrivant sur le vrai domaine.
    Le chemin et les parametres sont conserves. Inactif tant que
    MEMORA_PUBLIC_BASE_URL n'est pas un domaine hors onrender.com (dev, tests).
    Le point de controle Render (/health/) n'est jamais redirige.
    """

    LEGACY_SUFFIX = ".onrender.com"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        canonical = urlsplit(getattr(settings, "MEMORA_PUBLIC_BASE_URL", "") or "")
        canonical_host = (canonical.hostname or "").lower()
        if canonical_host and not canonical_host.endswith(self.LEGACY_SUFFIX):
            host = request.META.get("HTTP_HOST", "").split(":")[0].lower()
            if host.endswith(self.LEGACY_SUFFIX) and request.path != "/health/":
                target = f"{canonical.scheme or 'https'}://{canonical.netloc}{request.get_full_path()}"
                if request.method in ("GET", "HEAD"):
                    return HttpResponsePermanentRedirect(target)
                # 308 : le navigateur rejoue la requete avec la meme methode.
                response = HttpResponse(status=308)
                response["Location"] = target
                return response
        return self.get_response(request)


class SessionIdleTimeoutMiddleware:
    """Deconnecte un ORGANISATEUR reste inactif trop longtemps.

    Volontairement limite aux utilisateurs authentifies : la session d'un INVITE
    porte son quota d'envois (MEMORA_SESSION_UPLOAD_LIMIT) et ne doit pas etre
    reinitialisee, sinon le quota repart de zero a chaque expiration.

    L'horodatage d'activite n'est reecrit que toutes les
    MEMORA_SESSION_ACTIVITY_REFRESH_SECONDS, pour ne pas provoquer une ecriture
    de session a chaque requete.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        timeout = getattr(settings, "MEMORA_SESSION_IDLE_TIMEOUT_SECONDS", 0)
        user = getattr(request, "user", None)

        if timeout > 0 and user is not None and user.is_authenticated:
            now = time.time()
            last_activity = request.session.get(LAST_ACTIVITY_KEY)

            if last_activity and now - last_activity > timeout:
                logout(request)
                messages.info(
                    request,
                    "Vous avez été déconnecté après une période d'inactivité. "
                    "Reconnectez-vous pour reprendre.",
                )
                login_url = reverse(settings.LOGIN_URL)
                if request.method == "GET":
                    login_url = f"{login_url}?{urlencode({'next': request.get_full_path()})}"
                return redirect(login_url)

            refresh_after = getattr(settings, "MEMORA_SESSION_ACTIVITY_REFRESH_SECONDS", 60)
            if not last_activity or now - last_activity > refresh_after:
                request.session[LAST_ACTIVITY_KEY] = now

        return self.get_response(request)
