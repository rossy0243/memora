from django.core.management.base import BaseCommand, CommandError

from events.models import Event
from processing.models import GeneratedMovie
from processing.services import create_event_movie_job, process_generated_movie


class Command(BaseCommand):
    help = "Traite ou relance le film souvenir d'un evenement precis."

    def add_arguments(self, parser):
        parser.add_argument("event_id", type=int, help="ID de l'evenement a traiter.")
        parser.add_argument(
            "--include-processing",
            action="store_true",
            help="Autorise la reprise d'un film deja marque en cours.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Affiche le film cible sans lancer FFmpeg.",
        )

    def handle(self, *args, **options):
        event = self._get_event(options["event_id"])
        movie = self._get_or_create_movie(event, options["include_processing"])

        if options["dry_run"]:
            self.stdout.write(f"[dry-run] Film #{movie.pk} - {event.title}")
            return

        try:
            processed = process_generated_movie(movie)
        except Exception as exc:
            movie.status = GeneratedMovie.Status.FAILED
            movie.error_logs = f"process_event_movie: {exc}"
            movie.save(update_fields=["status", "error_logs", "updated_at"])
            self.stdout.write(
                self.style.ERROR(f"Film #{movie.pk} - {event.title}: echec.")
            )
            return

        self.stdout.write(
            f"Film #{processed.pk} - {event.title}: "
            f"{processed.get_status_display().lower()}."
        )

    def _get_event(self, event_id):
        try:
            return Event.objects.get(pk=event_id)
        except Event.DoesNotExist as exc:
            raise CommandError(f"Evenement #{event_id} introuvable.") from exc

    def _get_or_create_movie(self, event, include_processing):
        statuses = [GeneratedMovie.Status.PENDING]
        if include_processing:
            statuses.append(GeneratedMovie.Status.PROCESSING)

        movie = (
            event.generated_movies.filter(status__in=statuses)
            .order_by("-updated_at", "-created_at", "-pk")
            .first()
        )
        if movie:
            return movie

        if event.generated_movies.filter(status=GeneratedMovie.Status.PROCESSING).exists():
            raise CommandError(
                "Un film est deja en cours pour cet evenement. "
                "Relancez avec --include-processing pour le reprendre."
            )

        return create_event_movie_job(event)
