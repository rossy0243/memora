from django.core.management.base import BaseCommand

from processing.services import generate_event_movie, get_event_movie_schedule_at, get_scheduled_movie_events


class Command(BaseCommand):
    help = "Genere automatiquement les films souvenir planifies."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Affiche les films a generer sans lancer FFmpeg.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        events = get_scheduled_movie_events()

        if not events:
            self.stdout.write("Aucun film souvenir a generer.")
            return

        for event in events:
            scheduled_at = get_event_movie_schedule_at(event)
            if dry_run:
                self.stdout.write(
                    f"[dry-run] {event.title} serait genere "
                    f"(planifie le {scheduled_at:%Y-%m-%d %H:%M})."
                )
                continue

            movie = generate_event_movie(event)
            self.stdout.write(
                f"{event.title}: film {movie.get_status_display().lower()} "
                f"(id={movie.pk})."
            )
