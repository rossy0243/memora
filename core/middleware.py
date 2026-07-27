"""Middlewares transverses de Memora."""
import time
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.urls import reverse

LAST_ACTIVITY_KEY = "memora_last_activity"


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
