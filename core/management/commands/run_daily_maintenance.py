"""Entretien quotidien (cron memora-cleanup-expired-media) : suppressions, rappels, sauvegarde, controle.

Render n'execute qu'une commande sans shell : celle-ci enchaine les etapes. Une etape en echec
n'empeche pas les suivantes ; le processus sort en erreur a la fin (Render le signale).
"""
import logging

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from core import operations

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Nettoyage des medias expires, rappels aux organisateurs, sauvegarde de la base, controle d'exploitation."

    def handle(self, *args, **options):
        failed = []
        for label, command in (
            ("nettoyage des medias expires", "cleanup_expired_media"),
            ("rappels de conservation", "send_retention_reminders"),
            ("sauvegarde de la base", "backup_database_to_storage"),
        ):
            self.stdout.write(f"== {label}")
            try:
                call_command(command, stdout=self.stdout)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Daily maintenance step failed: %s", command)
                self.stdout.write(self.style.ERROR(f"ECHEC ({label}) : {type(exc).__name__}: {exc}"))
                failed.append(label)
            else:
                if command == "cleanup_expired_media":
                    operations.beat(operations.MAINTENANCE_CRON)
        self.stdout.write("== controle d'exploitation")
        issues, sent = operations.run_checks(watch_film_cron=True, watch_maintenance=True)
        self.stdout.write(f"{len(issues)} probleme(s) detecte(s), {sent} alerte(s) envoyee(s).")
        if failed:
            raise CommandError("Etapes en echec : " + ", ".join(failed))
