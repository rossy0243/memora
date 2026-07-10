from django.core.management.base import BaseCommand

from processing.services import get_pending_movie_jobs, process_generated_movie


class Command(BaseCommand):
    help = "Traite les films souvenir en attente."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=5,
            help="Nombre maximum de films a traiter pendant cette execution.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Affiche les jobs en attente sans lancer FFmpeg.",
        )

    def handle(self, *args, **options):
        limit = options["limit"]
        dry_run = options["dry_run"]
        movies = get_pending_movie_jobs(limit=limit)

        if not movies:
            self.stdout.write("Aucun film souvenir en attente.")
            return

        for movie in movies:
            if dry_run:
                self.stdout.write(f"[dry-run] Film #{movie.pk} - {movie.event.title}")
                continue

            processed = process_generated_movie(movie)
            self.stdout.write(
                f"Film #{processed.pk} - {processed.event.title}: "
                f"{processed.get_status_display().lower()}."
            )
