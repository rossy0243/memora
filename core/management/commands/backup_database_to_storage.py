"""Sauvegarde quotidienne de la base : export JSON compresse sur le stockage R2 (hors de Render).

    python manage.py backup_database_to_storage

Independant de la version de PostgreSQL (aucun pg_dump requis). Restauration sur une base NEUVE :
    python manage.py migrate
    python manage.py flush --noinput      # vide les donnees de depart creees par les migrations
    python manage.py loaddata memora-db-AAAAMMJJ-HHMMSS.json.gz
(restauration verifiee par le test BackupTests.test_a_backup_can_be_loaded_back)
Garde les MEMORA_BACKUP_KEEP dernieres sauvegardes. Contient des donnees personnelles : le
stockage est prive (URL signees), comme la base elle-meme.
"""
import gzip
import json
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.files.storage import default_storage
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core import operations

PREFIX = "backups"
EXCLUDED = ("contenttypes", "auth.permission", "sessions", "admin.logentry")


class Command(BaseCommand):
    help = "Exporte la base en JSON compresse sur le stockage et garde les dernieres sauvegardes."

    def handle(self, *args, **options):
        name = f"memora-db-{timezone.now():%Y%m%d-%H%M%S}.json.gz"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / name
            # Ecriture UTF-8 explicite (l'option --output suit l'encodage du systeme, cp1252 sous Windows).
            with gzip.open(path, "wt", encoding="utf-8") as stream:
                call_command("dumpdata", use_natural_foreign_keys=True, exclude=list(EXCLUDED), stdout=stream, verbosity=0)
            size = path.stat().st_size
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                objects = len(json.load(handle))
            if objects == 0:
                raise CommandError("La sauvegarde est vide : elle n'est pas enregistree.")
            with path.open("rb") as handle:
                stored = default_storage.save(f"{PREFIX}/{name}", File(handle))
        if default_storage.size(stored) != size:
            raise CommandError(f"Taille differente sur le stockage ({default_storage.size(stored)} au lieu de {size}).")
        self.stdout.write(f"Sauvegarde enregistree : {stored} ({size / 1024:.0f} Ko, {objects} objets).")

        files = sorted(default_storage.listdir(PREFIX)[1])
        for old in files[: max(len(files) - settings.MEMORA_BACKUP_KEEP, 0)]:
            default_storage.delete(f"{PREFIX}/{old}")
            self.stdout.write(f"  ancienne sauvegarde supprimee : {old}")
        operations.beat(operations.BACKUP)
