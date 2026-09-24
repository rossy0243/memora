"""Rend un livrable d'un evenement via Remotion (hors worker), pour tester la chaine.

    python manage.py render_movie_remotion <event_id> --deliverable=teaser --output=out.mp4

Ne touche pas au film stocke : ecrit un MP4 local. Sert a valider l'integration
Django -> Remotion sur de vrais medias avant de basculer le worker.

    python manage.py render_movie_remotion --list          # evenements et nombre de souvenirs
    python manage.py render_movie_remotion 2 --deliverable=teaser --upload-sample
        # depose l'exemple sur le stockage (dossier samples/, hors film de l'evenement) et affiche
        # un lien signe temporaire : utile depuis un job Render, dont le disque disparait ensuite.
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
        parser.add_argument("event_id", type=int, nargs="?")
        parser.add_argument("--list", action="store_true", help="Liste les evenements et leurs souvenirs.")
        parser.add_argument("--inventory", action="store_true", help="Liste les videos presentes sur le stockage, dossier par dossier.")
        parser.add_argument("--upload-sample", action="store_true", help="Depose le MP4 sur le stockage (samples/) et affiche un lien.")
        parser.add_argument("--deliverable", choices=list(_DELIVERABLE_DURATION), default="hero")
        parser.add_argument("--output", default=None)

    def handle(self, *args, **options):
        if options["inventory"]:
            from django.core.files.storage import default_storage

            def walk(folder):
                directories, files = default_storage.listdir(folder)
                for name in files:
                    yield f"{folder}/{name}" if folder else name
                for name in directories:
                    yield from walk(f"{folder}/{name}" if folder else name)

            folders = {}
            for path in walk(""):
                if path.lower().endswith((".mp4", ".mov", ".webm")):
                    entry = folders.setdefault(path.rsplit("/", 1)[0], [0, 0])
                    entry[0] += 1
                    try:
                        entry[1] += default_storage.size(path)
                    except Exception:
                        pass
            for folder, (count, size) in sorted(folders.items()):
                self.stdout.write(f"{folder}: {count} video(s), {size / 1e6:.1f} Mo")
            return
        if options["list"]:
            for event in Event.objects.order_by("pk"):
                uploads = event.guest_uploads.filter(is_deleted=False)
                videos = uploads.filter(media_type="video").count()
                self.stdout.write(
                    f"#{event.pk} « {event.title} » {event.event_date} : {uploads.count() - videos} photo(s), "
                    f"{videos} video(s), {uploads.values('session_key').distinct().count()} invite(s)"
                )
            return
        if not options["event_id"]:
            raise CommandError("Indiquez un identifiant d'evenement (ou --list).")
        try:
            event = Event.objects.get(pk=options["event_id"])
        except Event.DoesNotExist:
            raise CommandError(f"Evenement {options['event_id']} introuvable.")

        deliverable = options["deliverable"]
        max_duration = getattr(settings, _DELIVERABLE_DURATION[deliverable])
        uploads = list(
            get_movie_candidate_uploads(
                event, max_duration=max_duration, max_per_guest=settings.MEMORA_MOVIE_MAX_PER_GUEST.get(deliverable)
            )
        )
        if not uploads:
            raise CommandError("Aucun media exploitable pour cet evenement.")

        soundtrack = choose_movie_soundtrack(event, uploads)
        output = Path(options["output"] or f"remotion_{deliverable}_{event.pk}.mp4").resolve()

        self.stdout.write(
            f"Rendu {deliverable} : {len(uploads)} plan(s), piste « {soundtrack.track_name or 'aucune'} »..."
        )
        render_movie_with_remotion(event, uploads, soundtrack, output, deliverable=deliverable)
        self.stdout.write(self.style.SUCCESS(f"OK -> {output}"))
        guests = len({(u.device_id or u.device_cookie or u.session_key or f"u{u.pk}") for u in uploads})
        self.stdout.write(f"{len(uploads)} plan(s) de {guests} invite(s) different(s).")
        if options["upload_sample"]:
            from django.core.files import File
            from django.core.files.storage import default_storage

            with output.open("rb") as handle:
                stored = default_storage.save(f"samples/{output.name}", File(handle))
            self.stdout.write(f"LIEN {default_storage.url(stored)}")
