"""Rend un livrable d'un evenement via Remotion (hors worker), pour tester la chaine.

    python manage.py render_movie_remotion <event_id> --deliverable=teaser --output=out.mp4

Ne touche pas au film stocke : ecrit un MP4 local. Sert a valider l'integration
Django -> Remotion sur de vrais medias avant de basculer le worker.
"""
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from events.models import Event
from processing.remotion import render_movie_with_remotion
from processing.services import get_movie_candidate_uploads
from processing.soundtrack import choose_movie_soundtrack

_DELIVERABLE_DURATION = {
    "hero": "MEMORA_MOVIE_HERO_DURATION_SECONDS",
    "full": "MEMORA_MOVIE_FULL_DURATION_SECONDS",
    "teaser": "MEMORA_MOVIE_TEASER_DURATION_SECONDS",
}


class Command(BaseCommand):
    help = "Rend un livrable (hero/full/teaser) d'un evenement via Remotion."

    def add_arguments(self, parser):
        parser.add_argument("event_id", type=int)
        parser.add_argument("--deliverable", choices=list(_DELIVERABLE_DURATION), default="hero")
        parser.add_argument("--output", default=None)

    def handle(self, *args, **options):
        try:
            event = Event.objects.get(pk=options["event_id"])
        except Event.DoesNotExist:
            raise CommandError(f"Evenement {options['event_id']} introuvable.")

        deliverable = options["deliverable"]
        max_duration = getattr(settings, _DELIVERABLE_DURATION[deliverable])
        uploads = list(get_movie_candidate_uploads(event, max_duration=max_duration))
        if not uploads:
            raise CommandError("Aucun media exploitable pour cet evenement.")

        soundtrack = choose_movie_soundtrack(event, uploads)
        output = Path(options["output"] or f"remotion_{deliverable}_{event.pk}.mp4").resolve()

        self.stdout.write(
            f"Rendu {deliverable} : {len(uploads)} plan(s), piste « {soundtrack.track_name or 'aucune'} »..."
        )
        render_movie_with_remotion(event, uploads, soundtrack, output, deliverable=deliverable)
        self.stdout.write(self.style.SUCCESS(f"OK -> {output}"))
