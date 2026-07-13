from django.core.management.base import BaseCommand
from time import sleep

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
        parser.add_argument(
            "--loop",
            action="store_true",
            help="Continue a surveiller les jobs en attente.",
        )
        parser.add_argument(
            "--include-processing",
            action="store_true",
            help="Reprend aussi les films deja marques en cours.",
        )
        parser.add_argument(
            "--sleep",
            type=int,
            default=30,
            help="Secondes entre deux passages quand --loop est actif.",
        )

    def handle(self, *args, **options):
        while True:
            self.process_once(options)
            if not options["loop"]:
                return
            sleep(options["sleep"])

    def process_once(self, options):
        movies = get_pending_movie_jobs(
            limit=options["limit"],
            include_processing=options["include_processing"],
        )

        if not movies:
            self.stdout.write("Aucun film souvenir en attente.")
            return

        for movie in movies:
            if options["dry_run"]:
                self.stdout.write(f"[dry-run] Film #{movie.pk} - {movie.event.title}")
                continue

            processed = process_generated_movie(movie)
            self.stdout.write(
                f"Film #{processed.pk} - {processed.event.title}: "
                f"{processed.get_status_display().lower()}."
            )
