"""Rappels de conservation aux organisateurs (souvenirs bruts, puis film). Idempotent : un seul envoi.

    python manage.py send_retention_reminders            # envoie
    python manage.py send_retention_reminders --dry-run  # liste seulement
"""
from django.core.management.base import BaseCommand

from events import reminders


class Command(BaseCommand):
    help = "Prévient les organisateurs avant le retrait de leurs souvenirs et la suppression de leur film."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        originals = list(reminders.originals_reminders_due())
        films = list(reminders.film_reminders_due())
        sent_originals = sent_films = 0
        for event, removal in originals:
            if options["dry_run"]:
                self.stdout.write(f"[dry-run] souvenirs de « {event.title} » retirés le {removal:%d/%m/%Y} -> {event.organizer.email}")
            elif reminders.send_originals_reminder(event, removal):
                sent_originals += 1
        for event, deletion in films:
            if options["dry_run"]:
                self.stdout.write(f"[dry-run] film de « {event.title} » supprimé le {deletion:%d/%m/%Y} -> {event.organizer.email}")
            elif reminders.send_film_reminder(event, deletion):
                sent_films += 1
        if not options["dry_run"]:
            self.stdout.write(f"{sent_originals} rappel(s) souvenirs, {sent_films} rappel(s) film envoyés.")
