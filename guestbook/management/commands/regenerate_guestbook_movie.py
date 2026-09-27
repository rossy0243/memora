from django.core.management.base import BaseCommand, CommandError

from events.models import Event
from guestbook.services import queue_guestbook_movie
from processing.guestbook_montage import process_guestbook_movie


class Command(BaseCommand):
    help = (
        "Regenere en place le montage du livre d'or d'un evenement precis "
        "(remet le montage existant en attente puis le retraite "
        "immediatement), avec les reglages de production actuels "
        "(reduction de bruit, piste de fond)."
    )

    def add_arguments(self, parser):
        parser.add_argument("event_id", type=int)

    def handle(self, *args, **options):
        event_id = options["event_id"]
        try:
            event = Event.objects.get(pk=event_id)
        except Event.DoesNotExist as exc:
            raise CommandError(f"Evenement #{event_id} introuvable.") from exc

        movie = queue_guestbook_movie(event, trigger="organizer_request")
        if movie is None:
            raise CommandError(f"Aucun message de livre d'or pour l'evenement #{event_id}.")

        processed = process_guestbook_movie(movie)
        detail = (
            f" — {processed.error_message}"
            if processed.status == processed.Status.FAILED
            else ""
        )
        self.stdout.write(
            f"Livre d'or #{processed.pk} - {event.title}: {processed.get_status_display().lower()}{detail}"
        )
