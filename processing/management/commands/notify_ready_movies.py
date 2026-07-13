from django.core.management.base import BaseCommand

from processing.models import GeneratedMovie
from processing.services import notify_generated_movie_ready


class Command(BaseCommand):
    help = "Notifie les organisateurs dont le film souvenir est pret."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=20,
            help="Nombre maximum de notifications a traiter.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Affiche les films a notifier sans envoyer d'email.",
        )

    def handle(self, *args, **options):
        movies = self._get_movies(options["limit"])
        if not movies:
            self.stdout.write("Aucun film pret a notifier.")
            return

        for movie in movies:
            if options["dry_run"]:
                self.stdout.write(f"[dry-run] Film #{movie.pk} - {movie.event.title}")
                continue

            notified = notify_generated_movie_ready(movie)
            status = "notifie" if notified else "ignore"
            self.stdout.write(f"Film #{movie.pk} - {movie.event.title}: {status}.")

    def _get_movies(self, limit):
        queryset = (
            GeneratedMovie.objects.filter(
                status=GeneratedMovie.Status.COMPLETED,
                final_file__isnull=False,
                organizer_notified_at__isnull=True,
                event__organizer__email__gt="",
            )
            .exclude(final_file="")
            .select_related("event", "event__organizer")
            .order_by("generated_at", "pk")
        )
        return list(queryset[:limit])
