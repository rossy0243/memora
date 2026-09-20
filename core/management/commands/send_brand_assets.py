"""Envoie par e-mail les trois visuels de marque (assets/brand/*.png) depuis le contact Memora.

    python manage.py send_brand_assets adresse@exemple.fr [--reply-to contact@memoracd.site]

Le mail part de l'adresse d'envoi du site (celle du compte SMTP : le serveur refuse tout
autre expediteur) et les reponses vont au contact Memora de la configuration.
"""
import sys
from email.utils import parseaddr
from pathlib import Path

from django.conf import settings
from django.core.mail import EmailMessage
from django.core.management.base import BaseCommand, CommandError

from core.models import SiteConfiguration
from events.brand_assets import ASSETS

_BODY = """Bonjour,

Voici les trois visuels Memora pour vos réseaux sociaux, en haute définition et aux couleurs de la charte :

1. memora-logo-icone.png (2048 x 2048) : le monogramme seul. C'est la photo de profil : les réseaux la découpent en cercle, l'anneau reste entier.
2. memora-logo-nom.png (2400 x 1200) : le monogramme et le nom Memora. Pour un post, une vignette ou une signature.
3. memora-banniere.png (3000 x 1000) : le monogramme, le nom Memora et le slogan. Bandeau de couverture (X, LinkedIn, Facebook), le texte reste lisible même rogné.

Les versions vectorielles (SVG) sont disponibles sur simple demande.

Memora
Revivez votre événement à travers les yeux de vos invités.
"""


class Command(BaseCommand):
    help = "Envoie les trois visuels de marque par e-mail."

    def add_arguments(self, parser):
        parser.add_argument("recipient")
        parser.add_argument("--reply-to", default="", help="Adresse de reponse (defaut : contact Memora).")

    def handle(self, *args, **options):
        contact = options["reply_to"] or SiteConfiguration.current().effective_support_email
        sender = parseaddr(settings.DEFAULT_FROM_EMAIL)[1] or settings.DEFAULT_FROM_EMAIL
        folder = Path(settings.BASE_DIR) / "assets" / "brand"
        message = EmailMessage(
            "Memora - vos trois visuels pour les réseaux",
            _BODY,
            f"Memora <{sender}>",
            [options["recipient"]],
            reply_to=[contact] if contact else None,
        )
        for name in ASSETS:
            path = folder / f"{name}.png"
            if not path.exists():
                raise CommandError(f"Visuel introuvable : {path}")
            message.attach(path.name, path.read_bytes(), "image/png")
        self.stdout.write(f"CONFIG host={settings.EMAIL_HOST} expediteur={sender} reponse={contact or '-'} pieces_jointes={len(message.attachments)}")
        sys.stdout.flush()
        try:
            sent = message.send()
        except Exception as exc:
            raise CommandError(f"ECHEC de l'envoi : {type(exc).__name__}: {exc}") from exc
        self.stdout.write(f"RESULTAT messages_envoyes={sent}")
        sys.stdout.flush()
