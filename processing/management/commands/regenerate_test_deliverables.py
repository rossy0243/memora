from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from events.models import Event
from guestbook.services import queue_guestbook_movie
from processing.guestbook_montage import process_guestbook_movie
from processing.models import GeneratedMovie
from processing.services import process_generated_movie


class Command(BaseCommand):
    help = (
        "Regenere de force le film (heros/teaser) et le livre d'or de tous les "
        "evenements d'un organisateur, a partir des medias deja stockes (R2). "
        "Outil de test uniquement : contourne volontairement la protection qui "
        "empeche de regenerer un film deja termine (voir processing.services). "
        "Ne jamais utiliser sur un evenement client reel."
    )

    def add_arguments(self, parser):
        parser.add_argument("organizer_username", type=str)

    def handle(self, *args, **options):
        username = options["organizer_username"]
        user_model = get_user_model()
        try:
            organizer = user_model.objects.get(username=username)
        except user_model.DoesNotExist as exc:
            raise CommandError(f"Organisateur introuvable : {username}") from exc

        events = list(Event.objects.filter(organizer=organizer).order_by("pk"))
        if not events:
            raise CommandError(f"Aucun evenement pour l'organisateur {username}.")

        for event in events:
            upload_count = event.guest_uploads.filter(is_deleted=False).count()
            message_count = event.guestbook_messages.count()
            self.stdout.write(
                f"--- Evenement #{event.pk} « {event.title} » "
                f"(paye={event.is_paid}, souvenirs={upload_count}, "
                f"messages livre d'or={message_count}) ---"
            )

            movie = GeneratedMovie.objects.create(
                event=event,
                status=GeneratedMovie.Status.PENDING,
                progress_percent=5,
                progress_message="Regeneration manuelle (test).",
            )
            processed = process_generated_movie(movie)
            detail = (
                f" — {processed.error_logs}"
                if processed.status == GeneratedMovie.Status.FAILED
                else ""
            )
            self.stdout.write(
                f"  Film #{processed.pk}: {processed.get_status_display().lower()}{detail}"
            )

            guestbook_movie = queue_guestbook_movie(event, trigger="manual_test")
            if guestbook_movie is None:
                self.stdout.write("  Livre d'or : aucun message, rien a generer.")
                continue

            processed_guestbook = process_guestbook_movie(guestbook_movie)
            gb_detail = (
                f" — {processed_guestbook.error_message}"
                if processed_guestbook.status == processed_guestbook.Status.FAILED
                else ""
            )
            self.stdout.write(
                f"  Livre d'or #{processed_guestbook.pk}: "
                f"{processed_guestbook.get_status_display().lower()}{gb_detail}"
            )
