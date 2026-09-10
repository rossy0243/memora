from django.core.management.base import BaseCommand

from guestbook.services import (
    process_pending_guestbook_movies,
    queue_abandoned_guestbook_movies,
)


class Command(BaseCommand):
    help = (
        "Genere les montages du livre d'or en attente et rattrape les services "
        "que l'agent a oublie de terminer."
    )

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=3)
        parser.add_argument(
            "--skip-abandon",
            action="store_true",
            help="Ne rattrape pas les services non termines.",
        )
        parser.add_argument(
            "--include-processing",
            action="store_true",
            help="Reprend aussi les montages deja marques en cours.",
        )

    def handle(self, *args, **options):
        if not options["skip_abandon"]:
            queued = queue_abandoned_guestbook_movies()
            if queued:
                self.stdout.write(f"{queued} service(s) non termine(s) pris en charge.")

        processed = process_pending_guestbook_movies(
            limit=options["limit"],
            include_processing=options["include_processing"],
        )
        if not processed:
            self.stdout.write("Aucun montage de livre d'or en attente.")
            return
        for movie in processed:
            self.stdout.write(
                f"Montage livre d'or #{movie.pk} - {movie.event.title}: "
                f"{movie.get_status_display().lower()}."
            )
