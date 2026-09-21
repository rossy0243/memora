from django.core.management import call_command
from django.core.management.base import BaseCommand

from core import operations


class Command(BaseCommand):
    help = (
        "Passage du cron films : cree les films dus a J+1, puis vide la file "
        "d'attente (demandes manuelles, reprises d'echecs). Remplace la boucle "
        "de l'ancien worker permanent. Un seul appel — Render execute la commande "
        "sans shell, donc pas d'enchainement possible cote dockerCommand."
    )

    def handle(self, *args, **options):
        # Battement de coeur AVANT tout : la page de sante et les alertes savent que la tache
        # tourne, meme pendant un rendu long. Jamais bloquant pour les films.
        try:
            operations.beat(operations.FILM_CRON)
        except Exception:  # noqa: BLE001
            pass
        call_command("generate_scheduled_movies")
        call_command("process_pending_movies")
        # Montages du livre d'or : files a la fin de service de l'agent, plus le
        # rattrapage des services jamais termines.
        call_command("process_guestbook_movies")
        # Garde-fou : films en echec, bloques ou en retard -> e-mail a l'equipe. Ne leve jamais.
        operations.run_checks()
