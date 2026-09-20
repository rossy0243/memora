from django.core.management.base import BaseCommand, CommandError

from events.models import Event
from guestbook.models import GuestBookMovie
from guestbook.services import queue_guestbook_movie


class Command(BaseCommand):
    help = (
        "Affiche l'etat des montages du livre d'or ; avec --queue <id evenement>, "
        "le remet d'abord en file (il sera pris par le prochain passage du cron)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--queue", type=int, metavar="EVENT_ID")

    def handle(self, *args, **options):
        if options["queue"]:
            try:
                event = Event.objects.get(pk=options["queue"])
            except Event.DoesNotExist as exc:
                raise CommandError(f"Evenement {options['queue']} introuvable.") from exc
            movie = queue_guestbook_movie(event, trigger="manual_test")
            if movie is None:
                self.stdout.write("Aucun message dans le livre d'or : rien a monter.")
            else:
                self.stdout.write(f"Montage #{movie.pk} remis en file (statut {movie.status}).")

        for movie in GuestBookMovie.objects.select_related("event").order_by("pk"):
            self.stdout.write(
                f"#{movie.pk} evenement={movie.event_id} statut={movie.status} "
                f"{movie.progress_percent:.1f}% messages={movie.event.guestbook_messages.count()} "
                f"hd={'oui' if movie.final_file else 'non'} legere={'oui' if movie.light_file else 'non'} "
                f"provider={movie.render_provider} maj={movie.updated_at:%d/%m %H:%M} "
                f"erreur={(movie.error_message or '-')[:120]}"
            )
