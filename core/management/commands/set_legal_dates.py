"""Fixe les dates d'entree en vigueur des CGU et de la politique de confidentialite.

    python manage.py set_legal_dates --cgu 2026-09-21 --privacy 2026-09-21
    python manage.py set_legal_dates                      # affiche les valeurs actuelles

Sans date enregistree, les pages legales affichent « En vigueur au <date du jour> » : la date change
chaque jour, ce qui n'a aucune valeur juridique. Une date fixe indique quand la version actuelle est
entree en vigueur ; la changer seulement quand le texte change.
"""
from datetime import date

from django.core.management.base import BaseCommand, CommandError

from core.models import SiteConfiguration


def _parse(value):
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise CommandError(f"Date invalide « {value} » (format AAAA-MM-JJ).") from exc


class Command(BaseCommand):
    help = "Fixe (ou affiche) les dates d'entree en vigueur des CGU et de la politique de confidentialite."

    def add_arguments(self, parser):
        parser.add_argument("--cgu", help="Date des CGU, AAAA-MM-JJ.")
        parser.add_argument("--privacy", help="Date de la politique de confidentialite, AAAA-MM-JJ.")

    def handle(self, *args, **options):
        configuration = SiteConfiguration.current()
        changed = []
        if options["cgu"]:
            configuration.cgu_effective_date = _parse(options["cgu"])
            changed.append("cgu_effective_date")
        if options["privacy"]:
            configuration.privacy_effective_date = _parse(options["privacy"])
            changed.append("privacy_effective_date")
        if changed:
            configuration.save()
        self.stdout.write(
            f"CGU en vigueur au : {configuration.cgu_effective_date or 'NON FIXEE (date du jour affichee)'} - "
            f"Confidentialite en vigueur au : {configuration.privacy_effective_date or 'NON FIXEE (date du jour affichee)'}"
            + (f" (modifie : {', '.join(changed)})" if changed else "")
        )
