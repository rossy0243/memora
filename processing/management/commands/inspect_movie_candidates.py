from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from events.models import Event
from processing.services import get_movie_candidate_uploads
from uploads.models import GuestUpload


class Command(BaseCommand):
    help = (
        "Diagnostic en lecture seule : combien de souvenirs seraient retenus "
        "pour chaque livrable (hero/full/teaser) d'un evenement, avec le "
        "detail des parametres de selection utilises (voir "
        "processing.services._render_movie_with_remotion_pipeline)."
    )

    def add_arguments(self, parser):
        parser.add_argument("event_id", type=int)

    def handle(self, *args, **options):
        event_id = options["event_id"]
        try:
            event = Event.objects.get(pk=event_id)
        except Event.DoesNotExist as exc:
            raise CommandError(f"Evenement #{event_id} introuvable.") from exc

        total_approved = event.guest_uploads.filter(
            is_deleted=False, moderation_status=GuestUpload.ModerationStatus.APPROVED
        ).count()
        self.stdout.write(f"Evenement #{event.pk} — {event.title} : {total_approved} media(s) approuve(s)")

        variants = (
            ("hero", settings.MEMORA_MOVIE_HERO_DURATION_SECONDS, settings.MEMORA_MOVIE_MAX_PER_GUEST.get("hero")),
            ("full", settings.MEMORA_MOVIE_FULL_DURATION_SECONDS, settings.MEMORA_MOVIE_MAX_PER_GUEST.get("full")),
            ("teaser", settings.MEMORA_MOVIE_TEASER_DURATION_SECONDS, settings.MEMORA_MOVIE_MAX_PER_GUEST.get("teaser")),
        )
        for deliverable, max_duration, max_per_guest in variants:
            uploads = list(
                get_movie_candidate_uploads(event, max_duration=max_duration, max_per_guest=max_per_guest)
            )
            self.stdout.write(
                f"  {deliverable}: max_duration={max_duration}s max_per_guest={max_per_guest} "
                f"-> {len(uploads)} candidat(s)"
            )
