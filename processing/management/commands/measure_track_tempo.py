"""Mesure le tempo des pistes musicales pour caler les coupes du film sur la musique.

A relancer apres avoir ajoute une musique dans la bibliotheque, puis reporter les
valeurs affichees dans processing/soundtrack.py (TRACK_TEMPOS).

    python manage.py measure_track_tempo

Volontairement en Python pur (pas de numpy/librosa) : l'analyse tourne hors ligne,
le worker de rendu n'a donc aucune dependance supplementaire a installer.
"""
import array
import shutil
import subprocess
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

SAMPLE_RATE = 11025
HOP = 110  # ~10 ms -> enveloppe a ~100 Hz
ENV_RATE = SAMPLE_RATE / HOP
ANALYSE_SECONDS = 90
BPM_MIN = 60
BPM_MAX = 180


def _decode_to_pcm(ffmpeg_binary, path):
    result = subprocess.run(
        [
            ffmpeg_binary, "-v", "error", "-i", str(path),
            "-t", str(ANALYSE_SECONDS), "-ac", "1", "-ar", str(SAMPLE_RATE),
            "-f", "s16le", "-",
        ],
        capture_output=True,
        check=True,
    )
    samples = array.array("h")
    samples.frombytes(result.stdout[: len(result.stdout) // 2 * 2])
    return samples


def _onset_envelope(samples):
    """Energie par fenetre puis flux positif : les attaques ressortent."""
    energies = []
    for start in range(0, len(samples) - HOP, HOP):
        total = 0
        for value in samples[start:start + HOP]:
            total += value * value
        energies.append((total / HOP) ** 0.5)

    flux = [0.0]
    for index in range(1, len(energies)):
        delta = energies[index] - energies[index - 1]
        flux.append(delta if delta > 0 else 0.0)

    mean = sum(flux) / len(flux) if flux else 0.0
    return [value - mean for value in flux], energies


def _best_tempo(flux):
    """Autocorrelation du flux d'attaques sur la plage de tempo utile."""
    lag_min = int(ENV_RATE * 60 / BPM_MAX)
    lag_max = int(ENV_RATE * 60 / BPM_MIN)
    best_lag, best_score = lag_min, float("-inf")
    for lag in range(lag_min, lag_max + 1):
        score = 0.0
        for index in range(len(flux) - lag):
            score += flux[index] * flux[index + lag]
        score /= max(len(flux) - lag, 1)
        if score > best_score:
            best_score, best_lag = score, lag
    return 60.0 * ENV_RATE / best_lag, best_lag


def _first_strong_beat(energies, period_lag):
    """Premier pic marque : la musique doit demarrer sur ce temps."""
    window = energies[: min(len(energies), int(period_lag * 4))]
    if not window:
        return 0.0
    threshold = max(window) * 0.55
    for index, value in enumerate(window):
        if value >= threshold:
            return index / ENV_RATE
    return 0.0


class Command(BaseCommand):
    help = "Mesure le BPM et le premier temps de chaque piste de la bibliotheque musicale."

    def handle(self, *args, **options):
        ffmpeg_binary = shutil.which(settings.MEMORA_FFMPEG_BINARY)
        if not ffmpeg_binary:
            raise CommandError("ffmpeg introuvable : impossible de decoder les pistes.")

        music_dir = Path(settings.MEMORA_MOVIE_MUSIC_DIR)
        if not music_dir.exists():
            raise CommandError(f"Bibliotheque musicale absente : {music_dir}")

        tracks = sorted(
            path for path in music_dir.iterdir()
            if path.suffix.lower() in {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
        )
        if not tracks:
            self.stdout.write("Aucune piste a analyser.")
            return

        self.stdout.write("Reporter ces valeurs dans processing/soundtrack.py (TRACK_TEMPOS) :\n")
        self.stdout.write("TRACK_TEMPOS = {")
        for track in tracks:
            try:
                samples = _decode_to_pcm(ffmpeg_binary, track)
                flux, energies = _onset_envelope(samples)
                bpm, lag = _best_tempo(flux)
                offset = _first_strong_beat(energies, lag)
            except Exception as exc:
                self.stderr.write(f"    # {track.name} : echec de l'analyse ({exc})")
                continue
            self.stdout.write(f'    "{track.name}": ({bpm:.1f}, {offset:.2f}),')
        self.stdout.write("}")
