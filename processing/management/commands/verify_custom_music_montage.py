"""Verifie de bout en bout, sur CETTE machine et avec le stockage reel, que la
chanson televersee par un organisateur se retrouve bien dans le montage du livre d'or.

Cree un evenement TEMPORAIRE (sous le compte indique), y depose une chanson
reconnaissable (un la a 880 Hz) et deux messages synthetiques, genere le vrai
montage puis ANALYSE LE SON obtenu : la chanson doit etre audible sur les cartons,
baisser sous la voix et s'eteindre a la fin. L'evenement et tous ses fichiers sont
supprimes a la fin, quoi qu'il arrive.
"""
import array
import math
import subprocess
import tempfile
from datetime import date, timedelta
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError

from events.models import Event, EventType
from events.services import delete_event
from guestbook.models import GuestBookMessage, GuestBookMovie
from processing.guestbook_montage import process_guestbook_movie
from processing.soundtrack import choose_movie_soundtrack

SONG_HZ = 880
VOICE_HZ = 300


def _tone_power(samples, rate, freq):
    """Puissance de la composante `freq` (algorithme de Goertzel)."""
    n = len(samples)
    k = round(n * freq / rate)
    coeff = 2 * math.cos(2 * math.pi * k / n)
    s1 = s2 = 0.0
    for x in samples:
        s1, s2 = x + coeff * s1 - s2, s1
    return (s1 * s1 + s2 * s2 - coeff * s1 * s2) / (n * n)


def _db(power):
    return 10 * math.log10(power) if power > 0 else -120.0


class Command(BaseCommand):
    help = "Verifie que la chanson d'un organisateur est bien utilisee dans le montage du livre d'or."

    def add_arguments(self, parser):
        parser.add_argument("organizer_username", help="Compte sous lequel creer l'evenement temporaire.")

    def handle(self, *args, **options):
        try:
            organizer = get_user_model().objects.get(username=options["organizer_username"])
        except get_user_model().DoesNotExist as exc:
            raise CommandError("Organisateur introuvable.") from exc

        event = Event.objects.create(
            organizer=organizer,
            title="Verification chanson (temporaire)",
            event_type=EventType.objects.get(code="wedding"),
            event_date=date.today(),
        )
        self.failed = False
        try:
            with tempfile.TemporaryDirectory(prefix="memora_verif_") as tmp:
                self._verify(event, Path(tmp))
        finally:
            delete_event(event)
            self.stdout.write("Evenement temporaire et fichiers supprimes.")
        self.stdout.write("RESULTAT : " + ("ECHEC" if self.failed else "TOUT EST OK"))
        if self.failed:
            raise CommandError("Verification en echec.")

    def _check(self, label, condition, detail=""):
        self.failed = self.failed or not condition
        self.stdout.write(f"  {'OK    ' if condition else 'ECHEC '} {label} {detail}".rstrip())

    def _ffmpeg(self, *args, stdout=None):
        subprocess.run(
            [settings.MEMORA_FFMPEG_BINARY, "-hide_banner", "-loglevel", "error", "-y", *args],
            check=True, stdout=stdout,
        )

    def _samples(self, path, start, seconds):
        raw = subprocess.run(
            [settings.MEMORA_FFMPEG_BINARY, "-hide_banner", "-loglevel", "error", "-ss", str(start),
             "-t", str(seconds), "-i", str(path), "-ac", "1", "-ar", "8000", "-f", "s16le", "-"],
            capture_output=True, check=True,
        ).stdout
        data = array.array("h")
        data.frombytes(raw[: len(raw) // 2 * 2])
        return [value / 32768 for value in data]

    def _verify(self, event, work):
        song, msg1, msg2 = work / "song.mp3", work / "msg1.mp4", work / "msg2.webm"
        self._ffmpeg("-f", "lavfi", "-i", f"sine=frequency={SONG_HZ}:duration=45,tremolo=f=2:d=0.9",
                     "-c:a", "libmp3lame", "-b:a", "128k", str(song))
        self._ffmpeg("-f", "lavfi", "-i", "testsrc=size=1280x720:rate=30:duration=6",
                     "-f", "lavfi", "-i", f"sine=frequency={VOICE_HZ}:duration=6",
                     "-c:v", settings.MEMORA_MOVIE_VIDEO_ENCODER, "-c:a", "aac", "-shortest", str(msg1))
        with open(msg2, "wb") as target:  # comme MediaRecorder : ecrit en flux, sans duree
            self._ffmpeg("-f", "lavfi", "-i", "testsrc2=size=540x960:rate=30:duration=4",
                         "-f", "lavfi", "-i", f"sine=frequency={VOICE_HZ}:duration=4",
                         "-c:v", "libvpx", "-b:v", "800k", "-c:a", "libopus", "-shortest",
                         "-f", "webm", "pipe:1", stdout=target)

        self.stdout.write("1) Chanson de l'organisateur")
        with open(song, "rb") as handle:
            event.custom_music_file.save("Verification.mp3", File(handle), save=True)
        self._check("chanson enregistree dans le stockage", event.custom_music_file.storage.exists(event.custom_music_file.name),
                    event.custom_music_file.name)
        self._check("tempo mesure", event.measure_custom_music_tempo(), f"bpm={event.custom_music_bpm}")
        self._check("chanson choisie par le montage",
                    choose_movie_soundtrack(event, []).custom_event_id == event.pk)

        self.stdout.write("2) Montage reel")
        for path, guest, seconds in ((msg1, "Camille", 6), (msg2, "Tata Jeanne", 4)):
            message = GuestBookMessage(event=event, guest_name=guest, original_filename=path.name,
                                       file_size=path.stat().st_size, duration=timedelta(seconds=seconds))
            with open(path, "rb") as handle:
                message.media_file.save(path.name, File(handle), save=False)
            message.save()
        movie = GuestBookMovie.objects.create(event=event)
        process_guestbook_movie(movie)
        movie.refresh_from_db()
        self._check("montage termine", movie.status == GuestBookMovie.Status.COMPLETED,
                    f"statut={movie.status} {movie.error_message[:200]}")
        if movie.status != GuestBookMovie.Status.COMPLETED:
            return

        final = work / "final.mp4"
        with movie.final_file.open("rb") as source, open(final, "wb") as target:
            for chunk in source.chunks():
                target.write(chunk)

        self.stdout.write("3) Analyse du son du montage")
        intro = self._samples(final, 2.5, 2.0)
        card_song, card_voice = _db(_tone_power(intro, 8000, SONG_HZ)), _db(_tone_power(intro, 8000, VOICE_HZ))
        self._check("chanson audible sur le carton d'ouverture", card_song > -60, f"{card_song:.1f} dB")
        self._check("aucune voix sur le carton", card_voice < card_song - 20, f"voix {card_voice:.1f} dB")
        talk = self._samples(final, 9.8, 3.0)
        talk_voice, talk_song = _db(_tone_power(talk, 8000, VOICE_HZ)), _db(_tone_power(talk, 8000, SONG_HZ))
        self._check("voix audible pendant le message", talk_voice > -40, f"{talk_voice:.1f} dB")
        self._check("chanson baissee sous la voix (~ -9,5 dB attendus)", 6 <= card_song - talk_song <= 13,
                    f"baisse de {card_song - talk_song:.1f} dB")
        end = max(movie.duration.total_seconds() - 1.5, 0)
        end_song = _db(_tone_power(self._samples(final, end, 1.2), 8000, SONG_HZ))
        self._check("chanson en fondu de sortie a la fin", end_song < card_song - 6, f"{end_song:.1f} dB")
