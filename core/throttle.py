"""Protection contre les tentatives de mot de passe repetees (connexion, admin) et les rafales de
demandes de reinitialisation (« e-mail bombing »).

Les compteurs vivent en base (OperationalState) : partages par tous les processus du site, contrairement
au cache local de Django (un compteur par processus). Une ligne par (adresse IP, identifiant).

Connexion : 5 echecs en 15 min pour un meme (IP, identifiant) -> blocage 15 min ; ou 30 echecs en 15 min
depuis une meme IP tous identifiants confondus -> blocage 15 min. Un succes remet le compteur a zero.
"""
import hashlib
import logging
from datetime import datetime, timedelta

from django.contrib.auth.backends import ModelBackend
from django.utils import timezone

from .models import OperationalState
from .security import get_client_ip

logger = logging.getLogger(__name__)

LOGIN_WINDOW = timedelta(minutes=15)
LOGIN_PAIR_LIMIT = 5
LOGIN_IP_LIMIT = 30
LOGIN_LOCKOUT = timedelta(minutes=15)


def _digest(*parts):
    return hashlib.sha256("|".join(str(p).strip().lower() for p in parts).encode()).hexdigest()[:24]


def _load(key):
    state = OperationalState.objects.filter(key=key).first()
    return state.value if state else {}


def _save(key, value):
    OperationalState.objects.update_or_create(key=key, defaults={"value": value})


def _parse(value):
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _keys(request, username):
    ip = get_client_ip(request) or "?"
    return f"throttle:login:pair:{_digest(ip, username)}", f"throttle:login:ip:{_digest(ip)}"


def locked_until(request, username, now=None):
    """Date de fin du blocage si (IP, identifiant) ou l'IP est bloquee, sinon None."""
    now = now or timezone.now()
    latest = None
    for key in _keys(request, username):
        until = _parse(_load(key).get("locked_until"))
        if until and until > now and (latest is None or until > latest):
            latest = until
    return latest


def record_failure(request, username, now=None):
    now = now or timezone.now()
    pair_key, ip_key = _keys(request, username)
    for key, limit in ((pair_key, LOGIN_PAIR_LIMIT), (ip_key, LOGIN_IP_LIMIT)):
        state = _load(key)
        first = _parse(state.get("first_at"))
        if first is None or now - first > LOGIN_WINDOW:
            state = {"count": 0, "first_at": now.isoformat()}
        state["count"] = state.get("count", 0) + 1
        if state["count"] >= limit:
            state["locked_until"] = (now + LOGIN_LOCKOUT).isoformat()
            state["count"], state["first_at"] = 0, now.isoformat()
            logger.warning("Login throttled key=%s", key)
        _save(key, state)


def record_success(request, username):
    OperationalState.objects.filter(key=_keys(request, username)[0]).delete()


class ThrottledModelBackend(ModelBackend):
    """ModelBackend qui refuse de verifier un mot de passe tant que (IP, identifiant) est bloque.

    Couvre toutes les connexions (site et /admin/) sans toucher aux vues : `authenticate()` recoit la
    requete. Hors requete (shell, commandes), aucun blocage."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if request is None or username is None:
            return super().authenticate(request, username=username, password=password, **kwargs)
        if locked_until(request, username):
            return None
        user = super().authenticate(request, username=username, password=password, **kwargs)
        if user is None:
            record_failure(request, username)
        else:
            record_success(request, username)
        return user


# -- demandes de reinitialisation de mot de passe ------------------------------------------------------------
RESET_WINDOW = timedelta(hours=1)
RESET_IP_LIMIT = 5
RESET_EMAIL_LIMIT = 3


def allow_reset_request(request, email, now=None):
    """Compte la demande ; False si l'IP ou l'adresse a deja depasse sa limite sur l'heure."""
    now = now or timezone.now()
    allowed = True
    ip = get_client_ip(request) or "?"
    for key, limit in ((f"throttle:reset:ip:{_digest(ip)}", RESET_IP_LIMIT), (f"throttle:reset:email:{_digest(email)}", RESET_EMAIL_LIMIT)):
        state = _load(key)
        first = _parse(state.get("first_at"))
        if first is None or now - first > RESET_WINDOW:
            state = {"count": 0, "first_at": now.isoformat()}
        state["count"] += 1
        _save(key, state)
        if state["count"] > limit:
            allowed = False
    return allowed
