"""Envoie un e-mail de test avec la configuration d'envoi reelle.

Sert a verifier, depuis le serveur lui-meme (par ex. via un job Render), que le
SMTP configure fonctionne : `python manage.py send_test_email adresse@exemple.fr`.
Affiche la configuration utilisee (sans le mot de passe) puis le resultat.
"""
import sys

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Envoie un e-mail de test et affiche la configuration d'envoi utilisee."

    def add_arguments(self, parser):
        parser.add_argument("recipient")

    def handle(self, *args, **options):
        self.stdout.write(
            f"CONFIG backend={settings.EMAIL_BACKEND} host={settings.EMAIL_HOST} "
            f"port={settings.EMAIL_PORT} ssl={settings.EMAIL_USE_SSL} tls={settings.EMAIL_USE_TLS} "
            f"user={settings.EMAIL_HOST_USER} mdp_renseigne={bool(settings.EMAIL_HOST_PASSWORD)} "
            f"timeout={settings.EMAIL_TIMEOUT} expediteur={settings.DEFAULT_FROM_EMAIL}"
        )
        sys.stdout.flush()
        try:
            sent = send_mail(
                "Memora - test d'envoi",
                "Cet e-mail confirme que l'envoi depuis le serveur Memora fonctionne.",
                None,
                [options["recipient"]],
            )
        except Exception as exc:
            raise CommandError(f"ECHEC de l'envoi : {type(exc).__name__}: {exc}") from exc
        self.stdout.write(f"RESULTAT messages_envoyes={sent}")
        sys.stdout.flush()
