"""Teaser d'exemple monte a partir de videos DEJA presentes sur le stockage (R2), sans rien laisser en base.

    python manage.py render_sample_teaser --folders events/anniversaire-benedicte/uploads events/journee-du-22-juillet-2026/uploads

Un evenement temporaire et ses souvenirs sont crees DANS UNE TRANSACTION QUI EST ANNULEE a la fin : aucune
ligne n'est conservee et aucun fichier du stockage n'est modifie ni supprime. Le MP4 rendu est depose sous
samples/ avec un lien signe temporaire. Chaque video compte comme un invite different.
"""
import shutil
import tempfile
import uuid
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files import File
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from core.video import VideoDurationUnavailable, probe_video_duration
from events.models import Event, EventType
from processing.remotion import render_movie_with_remotion
from processing.services import get_movie_candidate_uploads
from processing.soundtrack import choose_movie_soundtrack
from uploads.models import GuestUpload

VIDEO_EXTENSIONS = (".mp4", ".mov", ".webm")


class _Rollback(Exception):
    pass


class Command(BaseCommand):
    help = "Monte un teaser d'exemple avec des videos deja sur le stockage (rien n'est conserve en base)."

    def add_arguments(self, parser):
        parser.add_argument("--folders", nargs="+", default=[], help="Dossiers du stockage a parcourir (recursif).")
        parser.add_argument("--purge-samples", action="store_true", help="Supprime les exemples deposes sous samples/ (seulement teaser-exemple*.mp4).")
        parser.add_argument("--min-mb", type=float, default=1.0, help="Ignore les videos plus petites (fichiers de test vides).")
        parser.add_argument("--max-files", type=int, default=24)
        parser.add_argument("--couple", default="Camille & Noé", help="Nom affiche dans le film.")

    def _walk(self, folder):
        directories, files = default_storage.listdir(folder)
        for name in files:
            yield f"{folder}/{name}"
        for name in directories:
            yield from self._walk(f"{folder}/{name}")

    def handle(self, *args, **options):
        if options["purge_samples"]:
            _directories, files = default_storage.listdir("samples")
            removed = [name for name in files if name.startswith("teaser-exemple") and name.endswith(".mp4")]
            for name in removed:
                default_storage.delete(f"samples/{name}")
            self.stdout.write(f"{len(removed)} exemple(s) supprime(s) : {', '.join(removed) or '-'}")
            return
        if not options["folders"]:
            raise CommandError("Indiquez --folders (ou --purge-samples).")
        paths = []
        for folder in options["folders"]:
            for path in self._walk(folder.strip("/")):
                if path.lower().endswith(VIDEO_EXTENSIONS) and default_storage.size(path) >= options["min_mb"] * 1_000_000:
                    paths.append(path)
        paths = sorted(paths)[: options["max_files"]]
        if not paths:
            raise CommandError("Aucune video assez grosse trouvee dans ces dossiers.")
        self.stdout.write(f"{len(paths)} video(s) retenue(s).")

        workdir = Path(tempfile.mkdtemp(prefix="sample-teaser-"))
        try:
            durations = {}
            for path in paths:
                try:
                    with default_storage.open(path, "rb") as source:
                        durations[path] = probe_video_duration(source, settings.MEMORA_FFPROBE_BINARY)
                except VideoDurationUnavailable:
                    self.stdout.write(f"  ignoree (duree illisible) : {path}")
            paths = [p for p in paths if p in durations]

            output = workdir / "teaser-exemple.mp4"
            try:
                with transaction.atomic():
                    self._render(paths, durations, output, options)
                    raise _Rollback
            except _Rollback:
                pass

            stored = default_storage.save(f"samples/teaser-exemple-{uuid.uuid4().hex[:6]}.mp4", File(output.open("rb")))
            self.stdout.write(f"LIEN {default_storage.url(stored)}")
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    def _render(self, paths, durations, output, options):
        organizer = get_user_model().objects.create_user(username=f"rehearsal-sample-{uuid.uuid4().hex[:6]}")
        event = Event.objects.create(
            organizer=organizer,
            title="Exemple teaser",
            couple_name=options["couple"],
            event_type=EventType.objects.get(code="wedding"),
            event_date=timezone.localdate(),
        )
        category = event.upload_categories.first()
        for index, path in enumerate(paths):
            seconds = durations[path]
            duration = seconds if isinstance(seconds, timedelta) else timedelta(seconds=float(seconds))
            GuestUpload.objects.create(
                event=event,
                category=category,
                media_file=path,
                media_type=GuestUpload.MediaType.VIDEO,
                original_filename=Path(path).name,
                file_size=default_storage.size(path),
                duration=duration,
                session_key=f"exemple-invite-{index}",
            )
        uploads = list(
            get_movie_candidate_uploads(
                event,
                max_duration=settings.MEMORA_MOVIE_TEASER_DURATION_SECONDS,
                max_per_guest=settings.MEMORA_MOVIE_MAX_PER_GUEST.get("teaser"),
            )
        )
        soundtrack = choose_movie_soundtrack(event, uploads)
        self.stdout.write(f"Rendu du teaser : {len(uploads)} plan(s), piste « {soundtrack.track_name or 'aucune'} »...")
        render_movie_with_remotion(event, uploads, soundtrack, output, deliverable="teaser")
        self.stdout.write(f"OK : {output.stat().st_size / 1e6:.1f} Mo")
