from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from events.models import Event
from processing.remotion import _probe_audio_duration_seconds
from processing.soundtrack import choose_movie_soundtrack, materialize_soundtrack


class Command(BaseCommand):
    help = (
        "Diagnostic en lecture seule : quelle piste serait retenue pour le film "
        "souvenir (hero/full/teaser) d'un evenement, et sa duree reelle (pour "
        "savoir si elle sera bouclee, voir remotion/src/MemoraFilm.tsx)."
    )

    def add_arguments(self, parser):
        parser.add_argument("event_id", type=int)

    def handle(self, *args, **options):
        event_id = options["event_id"]
        try:
            event = Event.objects.get(pk=event_id)
        except Event.DoesNotExist as exc:
            raise CommandError(f"Evenement #{event_id} introuvable.") from exc

        soundtrack = choose_movie_soundtrack(event, [])
        self.stdout.write(f"Evenement #{event.pk} — {event.title}")
        self.stdout.write(f"  Piste : {soundtrack.track_name or '(aucune)'}")
        self.stdout.write(f"  Raison : {soundtrack.reason}")

        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory(prefix="memora_inspect_music_") as work_dir:
            track_path, cleanup = materialize_soundtrack(soundtrack, Path(work_dir))
            if not track_path:
                self.stdout.write("  Duree : indisponible (aucune piste materialisable).")
                return
            duration = _probe_audio_duration_seconds(track_path, settings.MEMORA_FFPROBE_BINARY)
            if cleanup:
                Path(track_path).unlink(missing_ok=True)

        if duration is None:
            self.stdout.write("  Duree : illisible par ffprobe.")
            return

        minutes, seconds = divmod(int(duration), 60)
        self.stdout.write(f"  Duree : {minutes}m{seconds:02d}s ({duration:.1f}s)")
