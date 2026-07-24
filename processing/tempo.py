"""Mesure du tempo d'une piste musicale, en Python pur (ni numpy ni librosa).

L'analyse tourne hors ligne (import d'une piste, commande de mesure), le worker de
rendu n'a donc aucune dependance supplementaire a installer.

Principe : on decode l'audio en PCM mono basse frequence, on construit une enveloppe
d'energie, on en extrait le flux d'attaques, puis on autocorrele pour trouver la
periode dominante. Le premier pic marque donne le decalage du premier temps.
"""
import array
import shutil
import subprocess
from pathlib import Path

from django.conf import settings

SAMPLE_RATE = 11025
HOP = 110  # ~10 ms -> enveloppe a ~100 Hz
ENV_RATE = SAMPLE_RATE / HOP
ANALYSE_SECONDS = 90
BPM_MIN = 60
BPM_MAX = 180

SUPPORTED_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}


def ffmpeg_binary():
    return shutil.which(settings.MEMORA_FFMPEG_BINARY)


def _decode_to_pcm(binary, path):
    result = subprocess.run(
        [
            binary, "-v", "error", "-i", str(path),
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


def measure_tempo(path, binary=None):
    """Renvoie (bpm, decalage_premier_temps_en_s) pour un fichier audio local.

    Leve une exception si ffmpeg est absent ou si le fichier est illisible :
    aux appelants de decider quoi faire (best-effort a l'upload, erreur en commande).
    """
    binary = binary or ffmpeg_binary()
    if not binary:
        raise RuntimeError("ffmpeg introuvable : impossible de decoder la piste.")
    samples = _decode_to_pcm(binary, path)
    flux, energies = _onset_envelope(samples)
    bpm, lag = _best_tempo(flux)
    offset = _first_strong_beat(energies, lag)
    return round(bpm, 1), round(offset, 2)
