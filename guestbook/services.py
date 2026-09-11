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


def queue_abandoned_guestbook_movies():
    """File les livres d'or dont au moins un agent n'a jamais termine son service.

    Un service ouvert depuis plus de MEMORA_GUESTBOOK_MONTAGE_ABANDON_HOURS est
    cloture d'office et pris en charge par Memora — plusieurs agents pouvant
    travailler sur le meme evenement, la cloture de l'un n'attend pas les
    autres. Renvoie le nombre de montages nouvellement files.
    """
    cutoff = timezone.now() - timedelta(
        hours=settings.MEMORA_GUESTBOOK_MONTAGE_ABANDON_HOURS
    )
    stale_assignments = (
        GuestBookAssignment.objects.select_related("event")
        .filter(ended_at__isnull=True, started_at__lt=cutoff)
    )

    queued_events = set()
    now = timezone.now()
    for assignment in stale_assignments:
        assignment.ended_at = now
        assignment.save(update_fields=["ended_at", "updated_at"])
        if assignment.event_id in queued_events:
            continue
        if queue_guestbook_movie(assignment.event, trigger="auto_abandon"):
            queued_events.add(assignment.event_id)

    if queued_events:
        logger.info("Guestbook montage auto-queued for %s abandoned shift(s)", len(queued_events))
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
