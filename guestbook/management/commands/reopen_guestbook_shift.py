"""Remet une mission du livre d'or a zero (non demarree, non terminee) tant qu'aucun message n'existe.

    python manage.py reopen_guestbook_shift EVENT_ID AGENT_USERNAME

Sert quand un service a ete demarre ou cloture par erreur (par exemple ouvert en avance, puis
ferme automatiquement par le controle des services abandonnes). Refuse d'agir s'il y a deja des
messages : la mission n'est alors pas « vide » et ce n'est plus un simple remise a zero.
"""
from django.core.management.base import BaseCommand, CommandError

from guestbook.models import GuestBookAssignment


class Command(BaseCommand):
    help = "Remet a zero le service d'un agent sur un evenement (uniquement s'il n'y a aucun message)."

    def add_arguments(self, parser):
        parser.add_argument("event_id", type=int)
        parser.add_argument("agent_username")

    def handle(self, *args, **options):
        try:
            assignment = GuestBookAssignment.objects.select_related("event", "agent").get(
                event_id=options["event_id"], agent__username=options["agent_username"]
            )
        except GuestBookAssignment.DoesNotExist as exc:
            raise CommandError("Mission introuvable pour cet evenement et cet agent.") from exc

        count = assignment.event.guestbook_messages.count()
        if count:
            raise CommandError(f"{count} message(s) existent deja : remise a zero refusee.")

        assignment.started_at = None
        assignment.ended_at = None
        assignment.save(update_fields=["started_at", "ended_at", "updated_at"])
        self.stdout.write(f"Mission remise a zero : evenement {assignment.event_id}, agent {assignment.agent.username}.")
