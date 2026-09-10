from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Passage du cron films : cree les films dus a J+1, puis vide la file "
        "d'attente (demandes manuelles, reprises d'echecs). Remplace la boucle "
        "de l'ancien worker permanent. Un seul appel — Render execute la commande "
        "sans shell, donc pas d'enchainement possible cote dockerCommand."
    )

    def handle(self, *args, **options):
        call_command("generate_scheduled_movies")
        call_command("process_pending_movies")
        # Montages du livre d'or : files a la fin de service de l'agent, plus le
        # rattrapage des services jamais termines.
        call_command("process_guestbook_movies")
