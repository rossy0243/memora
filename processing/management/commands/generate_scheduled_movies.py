from django.core.management.base import BaseCommand

from processing.services import (
    create_event_movie_job,
    get_event_movie_schedule_at,
    get_scheduled_movie_events,
    process_generated_movie,
)


class Command(BaseCommand):
    help = "Genere automatiquement les films souvenir planifies."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Affiche les films a planifier sans creer de job.",
        )
        parser.add_argument(
            "--process-now",
            action="store_true",
            help="Traite immediatement les jobs crees au lieu d'attendre le worker.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        process_now = options["process_now"]
        events = get_scheduled_movie_events()

        if not events:
            self.stdout.write("Aucun film souvenir a planifier.")
            return

        for event in events:
            scheduled_at = get_event_movie_schedule_at(event)
            if dry_run:
                self.stdout.write(
                    f"[dry-run] {event.title} serait planifie "
                    f"(planifie le {scheduled_at:%Y-%m-%d %H:%M})."
                )
                continue

            movie = create_event_movie_job(event)
            if process_now:
                movie = process_generated_movie(movie)
            self.stdout.write(
                f"{event.title}: job film {movie.get_status_display().lower()} "
                f"(id={movie.pk})."
            )
