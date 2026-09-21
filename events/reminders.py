"""Rappels de conservation a l'organisateur : « telechargez vos souvenirs avant qu'ils soient retires ».

Deux rappels, chacun envoye UNE fois :
  - avant le retrait des souvenirs bruts (photos/videos des invites) : MEMORA_RETENTION_REMINDER_DAYS
    jours avant events.services.media_removal_date ;
  - avant la suppression definitive du film : MEMORA_DELIVERABLE_REMINDER_DAYS jours avant.
"""
import logging
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from processing.models import GeneratedMovie

from .models import Event
from .services import _event_dashboard_url, media_removal_date

logger = logging.getLogger(__name__)


def deliverable_deletion_date(event):
    """Jour ou le film est supprime pour de bon (voir la commande cleanup_expired_media)."""
    return event.event_date + timedelta(
        days=settings.MEMORA_DELIVERABLE_RETENTION_DAYS + settings.MEMORA_MEDIA_PURGE_GRACE_DAYS
    )


def originals_reminders_due(today=None):
    today = today or timezone.localdate()
    events = (
        Event.objects.filter(payment_status=Event.PaymentStatus.PAID, retention_reminder_sent_at__isnull=True)
        .exclude(organizer__email="")
        .select_related("organizer")
    )
    for event in events:
        removal = media_removal_date(event)
        if not (removal - timedelta(days=settings.MEMORA_RETENTION_REMINDER_DAYS) <= today < removal):
            continue
        if not event.guest_uploads.filter(is_deleted=False).exists():
            continue
        yield event, removal


def film_reminders_due(today=None):
    today = today or timezone.localdate()
    events = (
        Event.objects.filter(payment_status=Event.PaymentStatus.PAID, deliverable_reminder_sent_at__isnull=True)
        .exclude(organizer__email="")
        .select_related("organizer")
    )
    for event in events:
        deletion = deliverable_deletion_date(event)
        if not (deletion - timedelta(days=settings.MEMORA_DELIVERABLE_REMINDER_DAYS) <= today < deletion):
            continue
        movie = event.generated_movies.filter(status=GeneratedMovie.Status.COMPLETED, media_purged=False).exclude(final_file="").first()
        if movie:
            yield event, deletion


def _send(event, subject, lines):
    try:
        send_mail(subject, "\n".join(lines), settings.DEFAULT_FROM_EMAIL, [event.organizer.email], fail_silently=False)
    except Exception:  # noqa: BLE001 - un e-mail en echec n'arrete pas les autres rappels
        logger.exception("Retention reminder failed event=%s", event.pk)
        return False
    return True


def send_originals_reminder(event, removal):
    has_film = event.generated_movies.filter(status=GeneratedMovie.Status.COMPLETED, media_purged=False).exists()
    lines = [
        "Bonjour,",
        "",
        f"Les photos et vidéos envoyées par vos invités pour « {event.title} » seront retirées de Memora "
        f"le {removal:%d/%m/%Y}.",
        "",
        "Pour les garder, téléchargez l'archive complète (ZIP) depuis votre espace, avant cette date :",
        _event_dashboard_url(event),
        "",
    ]
    if has_film:
        lines += [f"Votre film souvenir, lui, reste disponible jusqu'au {deliverable_deletion_date(event):%d/%m/%Y}.", ""]
    lines += ["Merci de votre confiance.", "", "L'équipe Memora"]
    if not _send(event, f"Vos souvenirs « {event.title} » seront retirés le {removal:%d/%m/%Y}", lines):
        return False
    event.retention_reminder_sent_at = timezone.now()
    event.save(update_fields=["retention_reminder_sent_at", "updated_at"])
    return True


def send_film_reminder(event, deletion):
    lines = [
        "Bonjour,",
        "",
        f"Votre film souvenir « {event.title} » sera supprimé de Memora le {deletion:%d/%m/%Y}.",
        "",
        "Pensez à le télécharger avant cette date depuis votre espace :",
        _event_dashboard_url(event),
        "",
        "Merci de votre confiance.",
        "",
        "L'équipe Memora",
    ]
    if not _send(event, f"Votre film « {event.title} » sera supprimé le {deletion:%d/%m/%Y}", lines):
        return False
    event.deliverable_reminder_sent_at = timezone.now()
    event.save(update_fields=["deliverable_reminder_sent_at", "updated_at"])
    return True
