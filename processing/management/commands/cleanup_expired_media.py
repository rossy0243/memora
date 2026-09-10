"""Cycle de vie des medias sur R2.

Deux phases, exécutées à chaque passage du cron quotidien :

1. **Masquage** : quand `event_date + media_retention_days` est atteint, l'upload
   invité passe `is_deleted=True` (il disparaît du dashboard, du ZIP, du film).
   Le fichier reste sur R2.
2. **Purge** : après un délai de grâce supplémentaire
   (`MEMORA_MEDIA_PURGE_GRACE_DAYS`), le fichier est réellement supprimé de R2.
   La ligne est conservée comme pierre tombale (`media_purged=True`,
   `media_file` vidé) pour ne pas casser les compteurs / l'historique.
   Filet de sécurité : même sans film généré ni `deleted_at`, un média est
   purgé au plus tard à `event_date + retention + MEMORA_MEDIA_PURGE_BACKSTOP_DAYS`.

Les messages du livre d'or suivent la même règle de purge (sur la rétention de
l'événement + grâce). Le montage du livre d'or et le film souvenir sont des
livrables distincts et ne sont pas purgés ici.
"""
from datetime import timedelta
import logging

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from guestbook.models import GuestBookMessage
from uploads.models import GuestUpload


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Masque les medias invites expires puis purge leurs fichiers de R2."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Montre ce qui serait masque / purge sans rien modifier.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        today = timezone.localdate()
        now = timezone.now()
        grace = timedelta(days=settings.MEMORA_MEDIA_PURGE_GRACE_DAYS)
        backstop = timedelta(days=settings.MEMORA_MEDIA_PURGE_BACKSTOP_DAYS)

        masked = self._mask_expired_uploads(today, now, dry_run)
        purged_uploads = self._purge_upload_files(today, now, grace, backstop, dry_run)
        purged_messages = self._purge_guestbook_messages(today, grace, dry_run)

        prefix = "[dry-run] " if dry_run else ""
        self.stdout.write(
            self.style.SUCCESS(
                f"{prefix}{masked} media masque(s), "
                f"{purged_uploads} fichier(s) upload purge(s), "
                f"{purged_messages} message(s) livre d'or purge(s)."
            )
        )

    def _mask_expired_uploads(self, today, now, dry_run):
        uploads = (
            GuestUpload.objects.filter(is_deleted=False)
            .select_related("event")
            .only("id", "event__event_date", "event__media_retention_days")
        )
        expired_ids = [
            upload.id
            for upload in uploads.iterator()
            if upload.event.event_date
            + timedelta(days=upload.event.media_retention_days)
            <= today
        ]
        # Lignes deja masquees mais sans horodatage (donnees anterieures a ce
        # champ) : on les adopte pour que le delai de grace parte de maintenant.
        legacy = GuestUpload.objects.filter(is_deleted=True, deleted_at__isnull=True)

        if dry_run:
            logger.info("Cleanup dry-run mask count=%s legacy=%s", len(expired_ids), legacy.count())
            return len(expired_ids)

        updated = GuestUpload.objects.filter(id__in=expired_ids).update(
            is_deleted=True, deleted_at=now
        )
        legacy.update(deleted_at=now)
        logger.info("Cleanup masked=%s", updated)
        return updated

    def _purge_upload_files(self, today, now, grace, backstop, dry_run):
        candidates = GuestUpload.objects.filter(
            is_deleted=True, media_purged=False
        ).select_related("event").only(
            "id", "media_file", "deleted_at",
            "event__event_date", "event__media_retention_days",
        )

        purged = 0
        # Materialise : on ecrit ligne par ligne dans la boucle, on ne veut pas
        # d'un curseur serveur ouvert pendant ces writes.
        for upload in list(candidates):
            retention = timedelta(days=upload.event.media_retention_days)
            grace_reached = upload.deleted_at is not None and upload.deleted_at + grace <= now
            backstop_reached = upload.event.event_date + retention + backstop <= today
            if not (grace_reached or backstop_reached):
                continue

            if dry_run:
                purged += 1
                continue
            if not self._delete_file(upload, "upload"):
                continue
            upload.media_file = ""
            upload.media_purged = True
            upload.save(update_fields=["media_file", "media_purged"])
            purged += 1

        if dry_run:
            logger.info("Cleanup dry-run purge uploads count=%s", purged)
        else:
            logger.info("Cleanup purged_upload_files=%s", purged)
        return purged

    def _purge_guestbook_messages(self, today, grace, dry_run):
        candidates = (
            GuestBookMessage.objects.filter(media_purged=False)
            .select_related("event")
            .only(
                "id", "media_file",
                "event__event_date", "event__media_retention_days",
            )
        )

        purged = 0
        for message in list(candidates):
            retention = timedelta(days=message.event.media_retention_days)
            if message.event.event_date + retention + grace > today:
                continue

            if dry_run:
                purged += 1
                continue
            if not self._delete_file(message, "livre d'or"):
                continue
            message.media_file = ""
            message.media_purged = True
            message.save(update_fields=["media_file", "media_purged"])
            purged += 1

        if dry_run:
            logger.info("Cleanup dry-run purge guestbook count=%s", purged)
        else:
            logger.info("Cleanup purged_guestbook_messages=%s", purged)
        return purged

    def _delete_file(self, instance, label):
        """Supprime le fichier de R2. Renvoie True si on peut marquer la ligne
        comme purgee (fichier absent ou suppression reussie), False si le
        stockage a echoue — on retentera au prochain passage."""
        if not instance.media_file:
            return True
        try:
            instance.media_file.delete(save=False)
            return True
        except Exception as exc:  # storage indisponible : on retente plus tard
            logger.warning(
                "Cleanup file delete failed kind=%s pk=%s error=%s", label, instance.pk, exc
            )
            return False
