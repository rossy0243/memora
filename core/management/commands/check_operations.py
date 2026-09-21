"""Controle d'exploitation : detecte les problemes (film en echec, bloque, en retard, tache arretee,
sauvegarde absente) et previent l'equipe par e-mail, une fois par probleme (voir core.operations).

    python manage.py check_operations                # detecte et alerte
    python manage.py check_operations --dry-run      # detecte, n'envoie rien
    python manage.py check_operations --test-email   # envoie une alerte de test (verifie la livraison)
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from core import operations


class Command(BaseCommand):
    help = "Detecte les problemes d'exploitation et alerte par e-mail."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Liste les problemes sans envoyer d'e-mail.")
        parser.add_argument("--test-email", action="store_true", help="Envoie une alerte de test aux destinataires.")
        parser.add_argument("--watch-film-cron", action="store_true")
        parser.add_argument("--watch-maintenance", action="store_true")

    def handle(self, *args, **options):
        recipients = operations.alert_recipients()
        self.stdout.write("Destinataires des alertes : " + (", ".join(recipients) or "AUCUN (definir MEMORA_ALERT_EMAILS ou l'e-mail de contact)"))
        if options["test_email"]:
            issue = operations.Issue(
                f"test:{timezone.now().timestamp()}",
                "Test d'alerte",
                "Ceci est un test : si vous lisez ce message, les alertes d'exploitation arrivent bien.",
            )
            self.stdout.write("Alerte de test envoyee." if operations.send_alert(issue) else "ECHEC de l'envoi de l'alerte de test.")
            return
        kwargs = {"watch_film_cron": options["watch_film_cron"], "watch_maintenance": options["watch_maintenance"]}
        if options["dry_run"]:
            issues, sent = operations.collect_issues(**kwargs), 0
        else:
            issues, sent = operations.run_checks(**kwargs)
        alive, sentence = operations.film_cron_status()
        self.stdout.write(f"Tache des films : {'OK' if alive else 'SILENCIEUSE'} ({sentence})")
        self.stdout.write(f"{len(issues)} probleme(s) detecte(s), {sent} alerte(s) envoyee(s).")
        for issue in issues:
            self.stdout.write(f"  - {issue.title}")
