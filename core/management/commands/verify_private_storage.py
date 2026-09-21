"""Verifie en production que le stockage des fichiers sensibles est bien PRIVE.

    python manage.py verify_private_storage

Ecrit un petit fichier test dans le stockage des pieces d'identite ET dans celui des souvenirs, puis controle :
  - l'URL est signee et de courte duree (pieces d'identite : 5 minutes) ;
  - l'adresse SANS signature est refusee (aucun acces public) ;
  - l'adresse signee, elle, fonctionne ;
et supprime le fichier test. Ne touche a aucune donnee reelle.
"""
import urllib.error
import urllib.parse
import urllib.request
import uuid

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError

from accounts.storage import identity_document_storage


def _get(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"Range": "bytes=0-9"}), timeout=30) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code


class Command(BaseCommand):
    help = "Controle que les pieces d'identite et les souvenirs ne sont jamais accessibles sans URL signee."

    def handle(self, *args, **options):
        if getattr(settings, "MEMORA_STORAGE_BACKEND", "local") != "s3":
            self.stdout.write("Stockage local : rien a verifier (la commande sert en production, avec R2).")
            return
        failures = []
        for label, storage, prefix, max_expiry in (
            ("pieces d'identite", identity_document_storage(), "identity/verification", 300),
            ("souvenirs", default_storage, "verification", 3600),
        ):
            name = storage.save(f"{prefix}/{uuid.uuid4().hex}.txt", ContentFile(b"controle prive Memora"))
            try:
                signed = storage.url(name)
                query = urllib.parse.parse_qs(urllib.parse.urlparse(signed).query)
                expires = int(query.get("X-Amz-Expires", ["0"])[0])
                unsigned = signed.split("?", 1)[0]
                status_unsigned, status_signed = _get(unsigned), _get(signed)
                ok_signed = "X-Amz-Signature" in query and 0 < expires <= max_expiry
                ok_private = status_unsigned in (400, 401, 403)
                ok_works = status_signed in (200, 206)
                self.stdout.write(
                    f"  {label} : URL signee={'oui' if 'X-Amz-Signature' in query else 'NON'}, duree {expires} s (max {max_expiry}), "
                    f"sans signature -> {status_unsigned} {'(refuse)' if ok_private else '(ACCESSIBLE !)'}, avec signature -> {status_signed}"
                )
                if not (ok_signed and ok_private and ok_works):
                    failures.append(label)
            finally:
                storage.delete(name)
        if failures:
            raise CommandError("Stockage NON conforme : " + ", ".join(failures))
        self.stdout.write("OK : les pieces d'identite et les souvenirs ne sont accessibles qu'avec une URL signee de courte duree.")
