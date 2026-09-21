"""Notifications WhatsApp au proprietaire de Memora (nouvel evenement, alertes critiques).

Fournisseur : CallMeBot (https://www.callmebot.com/blog/free-api-whatsapp-messages/) - gratuit, un message
WhatsApp arrive sur VOTRE numero. Activation en 2 minutes : envoyer « I allow callmebot to send me messages »
au numero que CallMeBot indique, depuis votre WhatsApp ; il repond avec une cle (apikey). Variables :

    MEMORA_NOTIFY_WHATSAPP_APIKEY   la cle recue (sans elle, aucune notification : fonction desactivee)
    MEMORA_NOTIFY_WHATSAPP_PHONE    votre numero au format international (par defaut : le WhatsApp de la
                                    configuration Memora)

Garanties : envoi en arriere-plan avec delai court, JAMAIS bloquant ni source d'erreur pour l'utilisateur
(un echec est journalise et ignore) ; aucune donnee personnelle de l'organisateur (ni e-mail ni telephone) :
seulement le titre de l'evenement, le pseudo, la formule et un lien vers l'admin.
Pour un service officiel plus tard (API WhatsApp Business de Meta), ne remplacer que `_send`.
"""
import logging
import threading
import urllib.parse
import urllib.request

from django.conf import settings

logger = logging.getLogger(__name__)

CALLMEBOT_URL = "https://api.callmebot.com/whatsapp.php"
TIMEOUT_SECONDS = 8


def _phone_digits():
    from .models import SiteConfiguration

    raw = settings.MEMORA_NOTIFY_WHATSAPP_PHONE or SiteConfiguration.current().support_whatsapp
    return "".join(char for char in (raw or "") if char.isdigit())


def is_configured():
    return bool(settings.MEMORA_NOTIFY_WHATSAPP_APIKEY and _phone_digits())


def _send(phone, apikey, text):
    query = urllib.parse.urlencode({"phone": "+" + phone, "text": text, "apikey": apikey})
    with urllib.request.urlopen(f"{CALLMEBOT_URL}?{query}", timeout=TIMEOUT_SECONDS) as response:
        return response.status


def _deliver(phone, apikey, text):
    try:
        status = _send(phone, apikey, text)
        logger.info("WhatsApp notification sent status=%s", status)
    except Exception:  # noqa: BLE001 - une notification ne doit jamais faire echouer quoi que ce soit
        logger.warning("WhatsApp notification failed", exc_info=True)


def notify_owner(text, *, background=True):
    """Envoie `text` sur le WhatsApp du proprietaire. False si la fonction n'est pas configuree."""
    if not is_configured():
        return False
    phone, apikey = _phone_digits(), settings.MEMORA_NOTIFY_WHATSAPP_APIKEY
    if background:
        threading.Thread(target=_deliver, args=(phone, apikey, text), daemon=True).start()
    else:
        _deliver(phone, apikey, text)
    return True


def _admin_url(path):
    return f"{(settings.MEMORA_PUBLIC_BASE_URL or '').rstrip('/')}{path}"


def is_internal_account(user):
    """Comptes de test et d'outillage : jamais de notification pour eux."""
    name = getattr(user, "username", "") or ""
    return name.startswith(tuple(settings.MEMORA_NOTIFY_IGNORE_PREFIXES))


def notify_event_created(event):
    from django.urls import reverse

    if is_internal_account(event.organizer):
        return False
    plan = f"{event.plan.label} - {event.formatted_price}" if event.plan_id else event.formatted_price
    text = (
        "Memora - nouvel événement\n"
        f"« {event.title} » le {event.event_date:%d/%m/%Y}\n"
        f"Organisateur : {event.organizer.username}\n"
        f"Formule : {plan}\n"
        f"À activer / répondre : {_admin_url(reverse('admin:events_event_change', args=[event.pk]))}"
    )
    return notify_owner(text)
