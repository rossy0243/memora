from datetime import timedelta
import logging

from django.core.management.base import BaseCommand
from django.utils import timezone

from uploads.models import GuestUpload


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Mark guest uploads as deleted when their event retention period has expired."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show how many media would be marked as deleted without updating them.",
        )

    def handle(self, *args, **options):
        today = timezone.localdate()
        expired_ids = []

        uploads = (
            GuestUpload.objects.filter(is_deleted=False)
            .select_related("event")
            .only("id", "event__event_date", "event__media_retention_days")
        )

        for upload in uploads.iterator():
            expires_on = upload.event.event_date + timedelta(days=upload.event.media_retention_days)
            if expires_on <= today:
                expired_ids.append(upload.id)

        if options["dry_run"]:
            logger.info("Expired media cleanup dry-run count=%s", len(expired_ids))
            self.stdout.write(
                self.style.WARNING(f"{len(expired_ids)} media seraient marques comme supprimes.")
            )
            return

        updated = GuestUpload.objects.filter(id__in=expired_ids).update(is_deleted=True)
        logger.info("Expired media cleanup marked_deleted=%s", updated)
        self.stdout.write(self.style.SUCCESS(f"{updated} media marques comme supprimes."))
