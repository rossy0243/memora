"""Mesure le tempo des pistes du dossier musical (fallback filesystem).

Utile pour les pistes livrees en dur dans assets/music/. Pour les pistes ajoutees
via l'admin (modele MusicTrack), le tempo est mesure automatiquement a l'upload.

    python manage.py measure_track_tempo
"""
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from processing.tempo import SUPPORTED_AUDIO_EXTENSIONS, ffmpeg_binary, measure_tempo


class Command(BaseCommand):
    help = "Mesure le BPM et le premier temps de chaque piste du dossier musical."

    def handle(self, *args, **options):
        if not ffmpeg_binary():
            raise CommandError("ffmpeg introuvable : impossible de decoder les pistes.")

        music_dir = Path(settings.MEMORA_MOVIE_MUSIC_DIR)
        if not music_dir.exists():
            raise CommandError(f"Bibliotheque musicale absente : {music_dir}")

        tracks = sorted(
            path
            for path in music_dir.iterdir()
            if path.suffix.lower() in SUPPORTED_AUDIO_EXTENSIONS
        )
        if not tracks:
            self.stdout.write("Aucune piste a analyser.")
            return

        self.stdout.write("Reporter ces valeurs dans processing/soundtrack.py (TRACK_TEMPOS) :\n")
        self.stdout.write("TRACK_TEMPOS = {")
        for track in tracks:
            try:
                bpm, offset = measure_tempo(track)
            except Exception as exc:
                self.stderr.write(f"    # {track.name} : echec de l'analyse ({exc})")
                continue
            self.stdout.write(f'    "{track.name}": ({bpm}, {offset}),')
        self.stdout.write("}")
