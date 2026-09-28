from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError

from events.models import Event
from processing.models import GeneratedMovie
from processing.services import process_generated_movie


class Command(BaseCommand):
    help = (
        "Regenere en place le film souvenir d'un evenement precis (remet le "
        "job existant en attente puis le retraite immediatement), avec les "
        "reglages de production actuels. Equivalent programmatique de "
        "l'action admin « Regenerer le film souvenir » : ne cree pas de "
        "nouveau film, ne renvoie pas l'e-mail « film pret » (organizer_"
        "notified_at est conserve). --notify-email envoie, en plus, un court "
        "e-mail de confirmation a l'adresse donnee si (et seulement si) la "
        "regeneration reussit — pour l'operateur Memora, pas l'organisateur."
    )

    def add_arguments(self, parser):
        parser.add_argument("event_id", type=int)
        parser.add_argument(
            "--notify-email",
            default="",
            help="E-mail de confirmation envoye a cette adresse si la regeneration reussit.",
        )
        parser.add_argument(
            "--include-processing",
            action="store_true",
            help=(
                "Reprend aussi un film reste bloque en statut « en cours » (ex. processus "
                "tue net par un OOM, sans exception Python pour le repasser en echec). "
                "A n'utiliser que si on est sur qu'aucun job n'est reellement encore actif."
            ),
        )

    def handle(self, *args, **options):
        event_id = options["event_id"]
        try:
            event = Event.objects.get(pk=event_id)
        except Event.DoesNotExist as exc:
            raise CommandError(f"Evenement #{event_id} introuvable.") from exc

        statuses_to_exclude = (
            [] if options["include_processing"] else [GeneratedMovie.Status.PROCESSING]
        )
        movie = (
            event.generated_movies.exclude(status__in=statuses_to_exclude)
            .order_by("-created_at")
            .first()
        )
        if not movie:
            raise CommandError(f"Aucun film a regenerer pour l'evenement #{event_id}.")

        movie.status = GeneratedMovie.Status.PENDING
        movie.error_logs = ""
        movie.progress_percent = 0
        movie.progress_message = ""
        movie.save(
            update_fields=["status", "error_logs", "progress_percent", "progress_message", "updated_at"]
        )

        processed = process_generated_movie(movie)
        detail = (
            f" — {processed.error_logs}"
            if processed.status == GeneratedMovie.Status.FAILED
            else ""
        )
        self.stdout.write(
            f"Film #{processed.pk} - {event.title}: {processed.get_status_display().lower()}{detail}"
        )

        notify_email = options.get("notify_email")
        if notify_email and processed.status == GeneratedMovie.Status.COMPLETED:
            send_mail(
                subject=f"Film regenere avec succes - {event.title}",
                message=(
                    f"Le film souvenir de \"{event.title}\" a ete regenere avec succes.\n\n"
                    f"Heros : {'ok' if processed.final_file else 'absent'}\n"
                    f"Integrale : {'ok' if processed.full_file else 'absent'}\n"
                    f"Teaser : {'ok' if processed.teaser_file else 'absent'}\n"
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[notify_email],
                fail_silently=False,
            )
            self.stdout.write(f"E-mail de confirmation envoye a {notify_email}.")
