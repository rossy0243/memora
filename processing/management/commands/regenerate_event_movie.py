from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError

from events.models import Event
from processing.models import GeneratedMovie
from processing.services import _LIGHT_ENCODERS, process_generated_movie


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
        parser.add_argument(
            "--only",
            choices=["hero", "full", "teaser"],
            default="",
            help=(
                "Ne regenere que ce livrable : les deux autres, s'ils existent deja, "
                "restent inchanges (le pipeline les saute, voir "
                "_render_movie_with_remotion_pipeline). Utile pour livrer une "
                "correction ciblee (ex. nouvelle selection manuelle du teaser) sans "
                "retoucher a un heros/integrale deja bons."
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

        update_fields = ["status", "error_logs", "progress_percent", "progress_message", "updated_at"]
        movie.status = GeneratedMovie.Status.PENDING
        movie.error_logs = ""
        movie.progress_percent = 0
        movie.progress_message = ""

        only = options["only"]
        if only:
            # Cible un seul livrable : on ne vide que son fichier (et sa duree s'il
            # en a une), les deux autres restent tels quels pour que le pipeline les
            # saute (voir _render_movie_with_remotion_pipeline).
            file_field, duration_field = {
                "hero": ("final_file", None),
                "full": ("full_file", "full_duration"),
                "teaser": ("teaser_file", "teaser_duration"),
            }[only]
            setattr(movie, file_field, None)
            update_fields.append(file_field)
            if duration_field:
                setattr(movie, duration_field, None)
                update_fields.append(duration_field)
            _, light_field = _LIGHT_ENCODERS.get(only, (None, None))
            if light_field:
                setattr(movie, light_field, None)
                update_fields.append(light_field)
        elif not options["include_processing"]:
            # Regeneration volontaire (pas une reprise apres crash) : on repart
            # de zero sur les trois livrables. Sans ca, le pipeline (voir
            # _render_movie_with_remotion_pipeline) sauterait un livrable deja
            # present en le prenant pour un reste d'une tentative interrompue,
            # alors que l'organisateur veut justement du contenu neuf (nouvelle
            # musique, souvenirs rejetes...).
            movie.final_file = None
            movie.full_file = None
            movie.teaser_file = None
            movie.teaser_light_file = None
            movie.full_light_file = None
            movie.full_duration = None
            movie.teaser_duration = None
            update_fields += [
                "final_file", "full_file", "teaser_file", "teaser_light_file", "full_light_file",
                "full_duration", "teaser_duration",
            ]

        movie.save(update_fields=update_fields)

        processed = process_generated_movie(movie, only_deliverable=only or None)
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
