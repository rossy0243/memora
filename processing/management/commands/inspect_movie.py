from django.core.management.base import BaseCommand, CommandError

from events.models import Event
from processing.models import GeneratedMovie


class Command(BaseCommand):
    help = (
        "Diagnostic en lecture seule : liste tous les GeneratedMovie d'un evenement, "
        "pour verifier qu'un seul job n'a pas ete traite deux fois en parallele."
    )

    def add_arguments(self, parser):
        parser.add_argument("event_id", type=int)

    def handle(self, *args, **options):
        try:
            event = Event.objects.get(pk=options["event_id"])
        except Event.DoesNotExist as exc:
            raise CommandError(f"Evenement #{options['event_id']} introuvable.") from exc

        movies = event.generated_movies.order_by("created_at")
        self.stdout.write(f"Evenement #{event.pk} — {event.title} : {movies.count()} film(s)")
        for movie in movies:
            self.stdout.write(
                f"  film #{movie.pk} status={movie.status} provider={movie.render_provider} "
                f"created={movie.created_at:%H:%M:%S} updated={movie.updated_at:%H:%M:%S}"
            )
            self.stdout.write(f"    hero:   {movie.final_file.name if movie.final_file else '(vide)'}")
            self.stdout.write(f"    full:   {movie.full_file.name if movie.full_file else '(vide)'}")
            self.stdout.write(f"    teaser: {movie.teaser_file.name if movie.teaser_file else '(vide)'}")
