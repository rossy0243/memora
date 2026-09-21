"""Vide le contenu d'un evenement de test (souvenirs, films, livre d'or) sans toucher au QR code.

    python manage.py reset_event_content <id_evenement> --yes

L'evenement, son lien et sa cle d'acces (donc le QR code imprime), sa couverture, sa musique,
sa formule et son paiement restent intacts : on peut refaire un essai avec le meme QR.
Securite : refuse tout evenement qui n'est pas en mode test invites (« Activer pour test »).
"""
from django.core.management.base import BaseCommand, CommandError

from events.models import Event
from events.services import EventResetRefused, reset_event_content


class Command(BaseCommand):
    help = "Vide le contenu d'un evenement en mode test, en gardant l'evenement et son QR code."

    def add_arguments(self, parser):
        parser.add_argument("event_id", type=int)
        parser.add_argument("--yes", action="store_true", help="Confirme la suppression (sinon : simple apercu).")

    def handle(self, *args, **options):
        try:
            event = Event.objects.get(pk=options["event_id"])
        except Event.DoesNotExist as exc:
            raise CommandError(f"Evenement {options['event_id']} introuvable.") from exc

        self.stdout.write(
            f"Evenement {event.pk} « {event.title} » - mode test invites : {'oui' if event.guest_preview_enabled else 'NON'} - "
            f"{event.guest_uploads.count()} souvenir(s), {event.generated_movies.count()} film(s), "
            f"{event.guestbook_messages.count()} message(s) livre d'or."
        )
        if not options["yes"]:
            self.stdout.write("Apercu seulement : ajoutez --yes pour supprimer.")
            return
        try:
            counts = reset_event_content(event)
        except EventResetRefused as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            f"SUPPRIME : {counts['uploads']} souvenir(s), {counts['movies']} film(s), "
            f"{counts['guestbook_messages']} message(s) livre d'or, montage={counts['guestbook_movie']}, "
            f"{counts['files']} fichier(s) R2. Lien et QR code inchanges : {event.get_public_url()}"
        )
