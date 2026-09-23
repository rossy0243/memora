"""Diagnostic en lecture seule : missions du livre d'or, evenement par evenement.

    python manage.py inspect_assignments [event_id]

Utile pour verifier, avant ou pendant un evenement, qu'aucun agent n'a demarre son service en
avance (voir le garde-fou `event.is_upcoming` dans `guestbook.views.guestbook_capture`).
"""
from django.core.management.base import BaseCommand

from guestbook.models import GuestBookAssignment


class Command(BaseCommand):
    help = "Liste les missions du livre d'or (agent, dates, messages), sans rien modifier."

    def add_arguments(self, parser):
        parser.add_argument("event_id", type=int, nargs="?")

    def handle(self, *args, **options):
        assignments = GuestBookAssignment.objects.select_related("event", "agent").order_by("event_id", "agent_id")
        if options["event_id"]:
            assignments = assignments.filter(event_id=options["event_id"])

        if not assignments:
            self.stdout.write("Aucune mission.")
            return

        for assignment in assignments:
            event = assignment.event
            started_before_event = bool(
                assignment.started_at and assignment.started_at.date() < event.event_date
            )
            self.stdout.write(
                f"evenement={event.pk} « {event.title} » date={event.event_date} "
                f"a_venir={event.is_upcoming} test={event.guest_preview_enabled} | "
                f"agent={assignment.agent.username} demarree={assignment.started_at or '-'} "
                f"terminee={assignment.ended_at or '-'} messages={event.guestbook_messages.count()}"
                + (" *** DEMARREE AVANT LA DATE DE L'EVENEMENT ***" if started_before_event else "")
            )
