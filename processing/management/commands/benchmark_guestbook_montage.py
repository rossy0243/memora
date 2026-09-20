"""Mesure la vitesse reelle du montage du livre d'or sur CETTE machine.

Genere N messages video synthetiques (1080p, avec son, comme une camera de stand),
lance le vrai pipeline (cartons Remotion + FFmpeg + version legere) et affiche
le temps de chaque etape. N'ecrit ni en base ni sur R2 : a lancer sur le worker
(cron) pour savoir combien de temps prendra un vrai livre d'or, ou apres un
changement de reglage (workers, preset...).
"""
import os
import shutil
import subprocess
import tempfile
import time
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.conf import settings
from django.core.management.base import BaseCommand

from processing import guestbook_montage as montage


class Command(BaseCommand):
    help = "Chronometre le montage du livre d'or sur des messages synthetiques."

    def add_arguments(self, parser):
        parser.add_argument("--messages", type=int, default=20)
        parser.add_argument("--seconds", type=int, default=20, help="Duree de chaque message.")
        parser.add_argument("--size", default="1280x720", help="Resolution des messages sources.")

    def handle(self, *args, **options):
        count, seconds, size = options["messages"], options["seconds"], options["size"]
        encoder = settings.MEMORA_MOVIE_VIDEO_ENCODER
        self.stdout.write(
            f"encodeur={encoder} preset={getattr(settings, 'MEMORA_GUESTBOOK_MONTAGE_PRESET', '-')} "
            f"workers={montage._worker_count()} cpus={montage._available_cpus()} "
            f"(os.cpu_count={os.cpu_count()}) messages={count}x{seconds}s source={size}"
        )

        with tempfile.TemporaryDirectory(prefix="memora_bench_") as tmp:
            work = Path(tmp)
            source = work / "source.mp4"
            subprocess.run(
                [
                    settings.MEMORA_FFMPEG_BINARY, "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", f"testsrc2=size={size}:rate=30:duration={seconds}",
                    "-f", "lavfi", "-i", f"sine=frequency=300:duration={seconds}",
                    "-c:v", encoder, "-b:v", "3M", "-c:a", "aac", "-shortest", str(source),
                ],
                check=True,
            )

            names = ["Camille & Noé", "Tante Jeanne", "Élodie-Marie Ouédraogo", "Les voisins du 4ème", ""]
            messages = [
                SimpleNamespace(
                    original_filename="source.mp4",
                    media_file=SimpleNamespace(name="source.mp4"),
                    duration=timedelta(seconds=seconds),
                    guest_name=names[index % len(names)],
                )
                for index in range(count)
            ]
            event = SimpleNamespace(pk=0, slug="benchmark", title="Benchmark")
            sound = SimpleNamespace(has_track=False, mood="warm_lounge", first_beat_offset=0.0)

            stages = []
            started = time.monotonic()

            def report(fraction, message):
                label = message.split(" (")[0]
                if not stages or stages[-1][0] != label:
                    stages.append((label, time.monotonic() - started))

            with patch.object(
                montage, "_materialize_upload", lambda message, destination: shutil.copy(source, destination)
            ), patch.object(montage, "choose_movie_soundtrack", return_value=sound):
                result = montage.render_guestbook_montage(
                    event, messages, work / "hd.mp4", work / "light.mp4", report
                )
            total = time.monotonic() - started

            for label, at in stages:
                self.stdout.write(f"  a {at:6.0f}s : {label}")
            video = result.duration_seconds
            self.stdout.write(
                f"TOTAL {total:.0f}s pour {video:.0f}s de montage ({video / total:.2f}x le temps reel) "
                f"| HD {result.output_path.stat().st_size / 1e6:.0f} Mo"
                + (f" | legere {result.light_path.stat().st_size / 1e6:.0f} Mo" if result.light_path else " | pas de version legere")
            )
