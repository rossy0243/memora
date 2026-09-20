from django.core.management.base import BaseCommand

from core.models import SiteConfiguration


class Command(BaseCommand):
    help = (
        "Renseigne le contact affiche par Memora (page « mot de passe oublie », QR code a "
        "imprimer). Sans option, affiche la valeur actuelle."
    )

    def add_arguments(self, parser):
        parser.add_argument("--email", help="Adresse e-mail de contact.")
        parser.add_argument("--whatsapp", help="Numero WhatsApp au format international.")

    def handle(self, *args, **options):
        configuration = SiteConfiguration.current()
        changed = []
        if options["email"] is not None:
            configuration.support_email = options["email"].strip()
            changed.append("support_email")
        if options["whatsapp"] is not None:
            configuration.support_whatsapp = options["whatsapp"].strip()
            changed.append("support_whatsapp")
        if changed:
            configuration.save()
        self.stdout.write(
            f"Contact Memora : e-mail={configuration.effective_support_email or '-'} "
            f"whatsapp={configuration.support_whatsapp or '-'}"
            + (f" (modifie : {', '.join(changed)})" if changed else "")
        )
