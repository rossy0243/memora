from django.core.management.base import BaseCommand, CommandError

from events.models import Event
from processing.models import GeneratedMovie
from processing.services import process_generated_movie


class Command(BaseCommand):
    help = (
        "Regenere en place le film souvenir d'un evenement precis (remet le "
        "job existant en attente puis le retraite immediatement), avec les "
        "reglages de production actuels. Equivalent programmatique de "
        "l'action admin « Regenerer le film souvenir » : ne cree pas de "
        "nouveau film, ne renvoie pas l'e-mail « film pret » (organizer_"
        "notified_at est conserve)."
    )

    def add_arguments(self, parser):
        parser.add_argument("event_id", type=int)

    def handle(self, *args, **options):
        event_id = options["event_id"]
        try:
            event = Event.objects.get(pk=event_id)
        except Event.DoesNotExist as exc:
            raise CommandError(f"Evenement #{event_id} introuvable.") from exc

        movie = (
            event.generated_movies.exclude(status=GeneratedMovie.Status.PROCESSING)
            .order_by("-created_at")
            .first()
        )
        if not movie:
            raise CommandError(f"Aucun film a regenerer pour l'evenement #{event_id}.")

        movie.status = GeneratedMovie.Status.PENDING
        movie.error_logs = ""
        movie.progress_percent = 0
        movie.progress_message = ""
        movie.save(
            update_fields=["status", "error_logs", "progress_percent", "progress_message", "updated_at"]
        )

        processed = process_generated_movie(movie)
        detail = (
            f" — {processed.error_logs}"
            if processed.status == GeneratedMovie.Status.FAILED
            else ""
        )
        self.stdout.write(
            f"Film #{processed.pk} - {event.title}: {processed.get_status_display().lower()}{detail}"
        )
