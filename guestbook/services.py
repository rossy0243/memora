"""Orchestration du montage du livre d'or : mise en file, traitement, rattrapage.

Le rendu lui-meme vit dans `processing.guestbook_montage` (Remotion). Ici on
gere seulement le cycle de vie du `GuestBookMovie` et les declencheurs :
  - fin de service de l'agent (declencheur normal) ;
  - rattrapage automatique quand l'agent oublie de terminer son service ;
  - demande explicite de l'organisateur.
"""
import logging
from datetime import timedelta

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from .models import GuestBookAssignment, GuestBookMovie

logger = logging.getLogger(__name__)


def is_assigned_agent(user, event):
    """Vrai si `user` est un agent Memora affecte au livre d'or de cet evenement.

    Sert au « mode immersion » (point 10 de la mise a niveau post-mariage) :
    l'agent peut aussi capturer des souvenirs comme un invite, via le meme
    parcours public, mais sans la limite de 5 souvenirs par session ni le code
    d'acces invite — voir uploads.views.guest_upload_create."""
    if not user.is_authenticated or not hasattr(user, "agent_profile"):
        return False
    return GuestBookAssignment.objects.filter(event=event, agent=user).exists()


def has_open_shifts(event):
    """Vrai si au moins un agent a demarre son service sur cet evenement sans l'avoir termine.

    Un agent affecte mais qui n'a jamais commence ne bloque pas le montage."""
    return GuestBookAssignment.objects.filter(
        event=event, started_at__isnull=False, ended_at__isnull=True
    ).exists()


def queue_guestbook_movie(event, *, trigger):
    """Cree ou rearme le `GuestBookMovie` de l'evenement en attente de rendu.

    Sans effet s'il n'y a aucun message, ou si un montage est deja en attente /
    en cours. Un montage deja termine est relance (nouveaux messages possibles).
    """
    if not event.guestbook_messages.exists():
        return None

    movie, created = GuestBookMovie.objects.get_or_create(
        event=event,
        defaults={"status": GuestBookMovie.Status.PENDING, "trigger": trigger},
    )
    if created:
        logger.info("Guestbook montage queued event=%s trigger=%s", event.pk, trigger)
        return movie

    if movie.status in {GuestBookMovie.Status.PENDING, GuestBookMovie.Status.PROCESSING}:
        return movie

    movie.status = GuestBookMovie.Status.PENDING
    movie.trigger = trigger
    movie.error_message = ""
    movie.save(update_fields=["status", "trigger", "error_message", "updated_at"])
    logger.info("Guestbook montage re-queued event=%s trigger=%s", event.pk, trigger)
    return movie


def close_assignment_if_past_closing_time(assignment):
    """Cloture ce service si l'heure de fermeture du livre d'or est passee
    (Event.guestbook_closes_at, fixe a 23h59 le jour de l'evenement).

    Partage par le cron (rattrapage periodique) et par la vue de capture
    (fermeture immediate, sans attendre le prochain passage du cron). L'agent
    n'est plus jamais bloque par une inactivite prolongee — il peut enregistrer
    toute la soiree — seule cette heure fixe ferme le stand.

    Retourne (closed, queued) : closed est vrai si le service vient d'etre
    cloture ici ; queued est vrai si cette cloture a aussi mis le montage en
    file (dernier agent a terminer, voir has_open_shifts)."""
    if assignment.ended_at or timezone.now() < assignment.event.guestbook_closes_at:
        return False, False
    assignment.ended_at = timezone.now()
    assignment.save(update_fields=["ended_at", "updated_at"])
    if has_open_shifts(assignment.event):
        return True, False
    queued = bool(queue_guestbook_movie(assignment.event, trigger="auto_abandon"))
    return True, queued


def queue_abandoned_guestbook_movies():
    """Ferme d'office (et prend en charge le montage de) tout stand livre d'or
    dont l'heure de fermeture est passee mais qu'aucun agent n'a pense a
    terminer. Renvoie le nombre de montages nouvellement files."""
    open_assignments = GuestBookAssignment.objects.select_related("event").filter(ended_at__isnull=True)

    queued_events = set()
    for assignment in open_assignments:
        _closed, queued = close_assignment_if_past_closing_time(assignment)
        if queued:
            queued_events.add(assignment.event_id)

    if queued_events:
        logger.info("Guestbook montage auto-queued for %s closed-shift event(s)", len(queued_events))
    return len(queued_events)


def get_pending_guestbook_movies(limit=None, include_processing=False):
    stale_before = timezone.now() - timedelta(
        minutes=settings.MEMORA_MOVIE_PROCESSING_STALE_MINUTES
    )
    processing_filter = Q(status=GuestBookMovie.Status.PROCESSING)
    if not include_processing:
        processing_filter &= Q(started_at__lt=stale_before)

    queryset = (
        GuestBookMovie.objects.select_related("event")
        .filter(Q(status=GuestBookMovie.Status.PENDING) | processing_filter)
        .order_by("updated_at", "requested_at", "pk")
    )
    if limit:
        return list(queryset[:limit])
    return list(queryset)


def process_pending_guestbook_movies(limit=None, include_processing=False):
    from processing.guestbook_montage import process_guestbook_movie

    processed = []
    for movie in get_pending_guestbook_movies(limit=limit, include_processing=include_processing):
        processed.append(process_guestbook_movie(movie))
    return processed
