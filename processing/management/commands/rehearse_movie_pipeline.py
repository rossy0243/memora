"""Repetition generale du film automatique, avec un vrai volume de souvenirs.

    python manage.py rehearse_movie_pipeline --inventory
    python manage.py rehearse_movie_pipeline --photos 300 --videos 40 --email vous@exemple.fr

Cree un evenement de TEST (organisateur « rehearsal-bot », mode test invites), y depose des
souvenirs synthetiques au format que produit l'appli des invites (photos JPEG tirees du viseur,
videos de 10 s en MP4 fragmente comme sur iPhone ou en WebM sans duree comme sur Android, avec
son), puis fait passer l'evenement par le MEME chemin que la tache planifiee :
    planification (J+1 a 12 h) -> creation du job -> analyse -> selection -> rendu -> mail « film pret ».
Enfin il controle les livrables (ffprobe, son, images noires, planche-contact), le telechargement
par lien signe, la page du film, le ZIP complet des originaux, puis efface tout (sauf --keep).

Ne touche a aucun evenement reel : l'evenement de test porte le nom « Repetition generale ... ».
"""
import io
import json
import os
import random
import re
import subprocess
import tempfile
import time
import urllib.request
import uuid
from datetime import datetime, time as dtime, timedelta
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Sum
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from PIL import Image, ImageDraw

from events.models import Event, EventPlan, EventType
from events.services import delete_event
from processing.models import GeneratedMovie
from processing.services import (
    get_event_movie_schedule_at,
    get_scheduled_movie_events,
    iter_event_zip_chunks,
    process_generated_movie,
)
from uploads.models import GuestUpload

BOT_USERNAME = "rehearsal-bot"  # suffixe aleatoire ajoute a chaque execution : plusieurs repetitions peuvent tourner en parallele
TITLE_PREFIX = "Répétition générale"


def _run(command, **kwargs):
    return subprocess.run(command, capture_output=True, check=False, **kwargs)


def _encoders(ffmpeg):
    out = _run([ffmpeg, "-hide_banner", "-encoders"]).stdout.decode("utf-8", "replace")
    return {line.split()[1] for line in out.splitlines() if re.match(r"^\s[VAS][\w.]{5}\s", line)}


def _make_photo(rng, landscape):
    """Photo texturee au format d'une capture du viseur (jamais floue ni sombre)."""
    width, height = (1920, 1080) if landscape else (1080, 1920)
    top = tuple(rng.randint(40, 150) for _ in range(3))
    bottom = tuple(rng.randint(90, 220) for _ in range(3))
    gradient = Image.linear_gradient("L").resize((width, height))
    image = Image.composite(Image.new("RGB", (width, height), bottom), Image.new("RGB", (width, height), top), gradient)
    draw = ImageDraw.Draw(image)
    for _ in range(90):
        x0, y0 = rng.randint(0, width), rng.randint(0, height)
        x1, y1 = x0 + rng.randint(30, 420), y0 + rng.randint(30, 420)
        color = tuple(rng.randint(20, 255) for _ in range(3))
        if rng.random() < 0.5:
            draw.ellipse([x0, y0, x1, y1], fill=color)
        else:
            draw.rectangle([x0, y0, x1, y1], fill=color)
    noise = Image.effect_noise((width, height), 26).convert("RGB")
    image = Image.blend(image, noise, 0.10)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=88)
    return buffer.getvalue()


def _make_video(ffmpeg, encoders, index, landscape, container):
    """Video de 10 s avec son. MP4 fragmente (comme iOS) ou WebM sans duree (comme Android)."""
    width, height = (1920, 1080) if landscape else (1080, 1920)
    source = (
        f"testsrc2=size={width}x{height}:rate=30,hue=h={index * 29 % 360},noise=alls=10:allf=t[v]"
    )
    audio = f"sine=f={200 + index * 23}:r=48000[a1];anoisesrc=a=0.03:c=pink:r=48000[a2];[a1][a2]amix=inputs=2:duration=first[a]"
    graph = f"{source};{audio}"
    if container == "webm":
        video_codec = "libvpx" if "libvpx" in encoders else "libvpx-vp9"
        command = [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c=black:s=16x16:d=10",
            "-filter_complex", graph, "-map", "[v]", "-map", "[a]", "-t", "10",
            "-c:v", video_codec, "-b:v", "2500k", "-deadline", "realtime", "-cpu-used", "8", "-c:a", "libopus",
            "-f", "webm", "pipe:1",
        ]
        result = _run(command)
        return result.stdout, result.stderr
    video_codec = next((c for c in ("libx264", "h264_mf", "mpeg4") if c in encoders), None)
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory) / "clip.mp4"
        command = [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=16x16:d=10",
            "-filter_complex", graph, "-map", "[v]", "-map", "[a]", "-t", "10",
            "-c:v", video_codec, "-b:v", "8M", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
            "-movflags", "frag_keyframe+empty_moov+default_base_moof", str(target),
        ]
        result = _run(command)
        return (target.read_bytes() if target.exists() else b""), result.stderr


class Command(BaseCommand):
    help = "Repetition generale du film automatique avec un vrai volume (voir l'en-tete du module)."

    def add_arguments(self, parser):
        parser.add_argument("--inventory", action="store_true", help="Liste les evenements et leur volume, sans rien ecrire.")
        parser.add_argument("--photos", type=int, default=300)
        parser.add_argument("--videos", type=int, default=40)
        parser.add_argument("--unique-photos", type=int, default=30, help="Photos differentes generees, puis recyclees.")
        parser.add_argument("--unique-videos", type=int, default=8, help="Videos differentes generees, puis recyclees.")
        parser.add_argument("--email", default="", help="Adresse qui recoit le mail « film pret » (sinon aucune).")
        parser.add_argument("--keep", action="store_true", help="Ne supprime pas l'evenement de test a la fin.")
        parser.add_argument("--seed", type=int, default=7)

    # -- utilitaires d'affichage ---------------------------------------------------------
    def say(self, text=""):
        self.stdout.write(text)
        self.stdout.flush()

    def verify(self, label, condition, detail=""):
        self.results.append(bool(condition))
        self.say(f"  {'OK    ' if condition else 'ECHEC '} {label} {detail}".rstrip())

    # -- inventaire -------------------------------------------------------------------------
    def _inventory(self):
        for event in Event.objects.order_by("pk"):
            uploads = event.guest_uploads.all()
            photos = uploads.filter(media_type="image").count()
            videos = uploads.filter(media_type="video").count()
            size = uploads.aggregate(total=Sum("file_size"))["total"] or 0
            movies = event.generated_movies.count()
            self.say(
                f"evenement {event.pk} « {event.title} » date={event.event_date} paye={event.is_paid} actif={event.is_active} "
                f"test={event.guest_preview_enabled} souvenirs={photos} photo(s)+{videos} video(s) ({size / 1e6:.0f} Mo) films={movies}"
            )

    # -- graine ---------------------------------------------------------------------------------
    def _create_event(self):
        self.bot_username = f"{BOT_USERNAME}-{uuid.uuid4().hex[:6]}"
        user, _ = get_user_model().objects.get_or_create(username=self.bot_username)
        user.set_unusable_password()
        user.email = self.options["email"] or ""
        user.save()
        plan = EventPlan.objects.filter(code="grand-jour").first() or EventPlan.default_plan()
        event = Event.objects.create(
            organizer=user,
            title=f"{TITLE_PREFIX} {timezone.localtime():%Y%m%d-%H%M%S}",
            couple_name="Camille & Noé",
            event_type=EventType.objects.get(code="wedding"),
            plan=plan,
            event_date=timezone.localdate() - timedelta(days=2),
            welcome_message="Bienvenue à notre répétition.",
        )
        event.mark_paid(provider="rehearsal")
        event.guest_preview_enabled = True
        event.save()
        return event

    def _seed_uploads(self, event, ffmpeg):
        rng = random.Random(self.options["seed"])
        encoders = _encoders(ffmpeg)
        categories = list(event.upload_categories.all())
        n_photos, n_videos = self.options["photos"], self.options["videos"]

        started = time.time()
        photos = [_make_photo(rng, landscape=(i % 4 == 0)) for i in range(min(self.options["unique_photos"], n_photos))]
        videos = []
        for i in range(min(self.options["unique_videos"], n_videos)):
            container = "webm" if i % 3 == 2 else "mp4"
            data, err = _make_video(ffmpeg, encoders, i, landscape=(i % 5 == 4), container=container)
            if not data:
                self.say(f"  (video {i} {container} non generee : {err.decode('utf-8', 'replace')[:160]})")
                continue
            videos.append((container, data))
        self.say(f"  medias sources : {len(photos)} photo(s) ({sum(map(len, photos)) / len(photos) / 1e3:.0f} Ko en moyenne), "
                 f"{len(videos)} video(s) ({sum(len(d) for _, d in videos) / max(len(videos), 1) / 1e6:.1f} Mo en moyenne) en {time.time() - started:.0f} s")
        if n_videos and not videos:
            raise CommandError("Aucune video synthetique n'a pu etre generee (encodeur ffmpeg manquant ?).")

        started = time.time()
        created = []
        for i in range(n_photos):
            upload = GuestUpload(
                event=event, category=categories[i % len(categories)], media_type="image",
                original_filename=f"memora-photo-{i:04d}.jpg", file_size=len(photos[i % len(photos)]),
                session_key=f"reh-{i % 60}",
            )
            upload.media_file.save(upload.original_filename, ContentFile(photos[i % len(photos)]), save=True)
            created.append(upload)
        for i in range(n_videos):
            container, data = videos[i % len(videos)]
            name = f"memora-video-{i:04d}.{container}"
            upload = GuestUpload(
                event=event, category=categories[(i * 3) % len(categories)], media_type="video",
                original_filename=name, file_size=len(data), duration=timedelta(seconds=10), session_key=f"reh-{i % 60}",
            )
            upload.media_file.save(name, ContentFile(data), save=True)
            created.append(upload)
        # Reparti sur une soiree (18 h -> 1 h) : les chapitres du film suivent l'heure d'arrivee.
        base = timezone.make_aware(datetime.combine(event.event_date, dtime.min)) + timedelta(hours=18)
        rng.shuffle(created)
        for position, upload in enumerate(created):
            GuestUpload.objects.filter(pk=upload.pk).update(uploaded_at=base + timedelta(seconds=position * (7 * 3600 // max(len(created), 1))))
        total = event.guest_uploads.aggregate(total=Sum("file_size"))["total"] or 0
        self.say(f"  {len(created)} souvenirs deposes sur le stockage ({total / 1e6:.0f} Mo) en {time.time() - started:.0f} s")

    # -- controles des livrables -----------------------------------------------------------------
    def _probe(self, path):
        probe = _run([settings.MEMORA_FFPROBE_BINARY, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)])
        return json.loads(probe.stdout or b"{}")

    def _inspect(self, label, field, sheet_prefix):
        if not field:
            self.verify(f"{label} : fichier present", False)
            return None
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "film.mp4"
            with field.open("rb") as source, path.open("wb") as target:
                while True:
                    chunk = source.read(8 * 1024 * 1024)
                    if not chunk:
                        break
                    target.write(chunk)
            info = self._probe(path)
            streams = info.get("streams", [])
            video = next((s for s in streams if s.get("codec_type") == "video"), {})
            audio = next((s for s in streams if s.get("codec_type") == "audio"), {})
            duration = float(info.get("format", {}).get("duration") or 0)
            self.say(
                f"  {label} : {path.stat().st_size / 1e6:.1f} Mo, {duration:.0f} s, {video.get('codec_name')} "
                f"{video.get('width')}x{video.get('height')} @{video.get('r_frame_rate')}, audio={audio.get('codec_name')}"
            )
            self.verify(f"{label} : video lisible (H.264, durée > 20 s)", video.get("codec_name") == "h264" and duration > 20)
            self.verify(f"{label} : piste audio presente", bool(audio))
            mean_volume = None
            if audio:
                probe = _run([settings.MEMORA_FFMPEG_BINARY, "-hide_banner", "-i", str(path), "-af", "volumedetect", "-vn", "-f", "null", "-"])
                match = re.search(r"mean_volume:\s*(-?[\d.]+) dB", probe.stderr.decode("utf-8", "replace"))
                mean_volume = float(match.group(1)) if match else None
                self.verify(f"{label} : son audible (volume moyen {mean_volume} dB)", mean_volume is not None and mean_volume > -45)
            # Images : pas de noir, planche-contact.
            frames, blacks = [], 0
            count = 12
            for k in range(count):
                moment = duration * (k + 0.5) / count
                shot = _run([settings.MEMORA_FFMPEG_BINARY, "-hide_banner", "-loglevel", "error", "-ss", f"{moment:.2f}", "-i", str(path),
                             "-frames:v", "1", "-vf", "scale=320:-2", "-f", "image2pipe", "-vcodec", "png", "pipe:1"])
                if shot.stdout:
                    frame = Image.open(io.BytesIO(shot.stdout)).convert("RGB")
                    frames.append(frame)
                    if sum(frame.convert("L").resize((1, 1)).getdata()) < 6:
                        blacks += 1
            self.verify(f"{label} : aucune image noire sur {len(frames)} echantillons", frames and blacks == 0, f"({blacks} noire(s))")
            if frames:
                width, height = frames[0].size
                columns = 4 if width >= height else 6
                rows = -(-len(frames) // columns)
                sheet = Image.new("RGB", (columns * width, rows * height), (20, 20, 20))
                for k, frame in enumerate(frames):
                    sheet.paste(frame, ((k % columns) * width, (k // columns) * height))
                buffer = io.BytesIO()
                sheet.save(buffer, format="JPEG", quality=85)
                name = default_storage.save(f"rehearsal/{sheet_prefix}-{label}.jpg", ContentFile(buffer.getvalue()))
                self.temp_names.append(name)
                self.say(f"  planche-contact {label} : {default_storage.url(name)}")
            return {"duration": duration, "size": path.stat().st_size}

    # -- deroule -------------------------------------------------------------------------------------
    def handle(self, *args, **options):
        self.options = options
        self.results = []
        self.temp_names = []
        if options["inventory"]:
            return self._inventory()

        ffmpeg = settings.MEMORA_FFMPEG_BINARY
        self.say(f"Reglages : rendu={settings.MEMORA_MOVIE_RENDER_PROVIDER} livrables={sorted(settings.MEMORA_MOVIE_DELIVERABLES)} "
                 f"analyse={getattr(settings, 'MEMORA_AI_ANALYSIS_PROVIDER', '?')} runway={settings.MEMORA_RUNWAY_ENABLED} "
                 f"film {settings.MEMORA_MOVIE_WIDTH}x{settings.MEMORA_MOVIE_HEIGHT} duree max heros={settings.MEMORA_MOVIE_HERO_DURATION_SECONDS} s "
                 f"stockage={settings.MEMORA_STORAGE_BACKEND}")

        event = self._create_event()
        self.say(f"\n1) Evenement de test {event.pk} « {event.title} » (date {event.event_date}, mode test)")
        try:
            self.say("\n2) Depot des souvenirs")
            self._seed_uploads(event, ffmpeg)
            self._run_and_check(event)
        finally:
            if options["keep"]:
                self.say(f"\nEvenement conserve : {event.pk} (organisateur {BOT_USERNAME}).")
            else:
                self._cleanup(event)
        ok = all(self.results)
        self.say(f"\nRESULTAT : {'TOUT EST OK' if ok else 'IL Y A DES ECHECS'} ({sum(self.results)}/{len(self.results)} controles)")
        if not ok:
            raise CommandError("Repetition generale : des controles ont echoue.")

    def _run_and_check(self, event):
        self.say("\n3) Planification : le cron voit-il l'evenement ?")
        self.say(f"  film prevu le {get_event_movie_schedule_at(event):%Y-%m-%d %H:%M} (heure de Paris), maintenant {timezone.localtime():%Y-%m-%d %H:%M}")
        self.verify("l'evenement est retenu par la planification (J+1 a 12 h)", event in get_scheduled_movie_events())
        call_command("generate_scheduled_movies")
        movie = event.generated_movies.first()
        self.verify("un film « en attente » est cree", movie is not None and movie.status == GeneratedMovie.Status.PENDING)
        if movie is None:
            return

        self.say("\n4) Generation (analyse, selection, montage, rendu, badge, teaser)")
        started = time.time()
        movie = process_generated_movie(movie)
        elapsed = time.time() - started
        movie.refresh_from_db()
        self.say(f"  duree totale de generation : {elapsed:.0f} s ({elapsed / 60:.1f} min) - statut={movie.status} - rendu={movie.render_provider}")
        self.say(f"  musique : {movie.music_track!r} ({movie.music_mood}) - message : {movie.progress_message!r}")
        self.verify("film termine avec succes", movie.status == GeneratedMovie.Status.COMPLETED, movie.error_logs[:300])
        if movie.status != GeneratedMovie.Status.COMPLETED:
            return
        clips = movie.edit_decision_data.get("clips", [])
        kinds = {"image": sum(1 for c in clips if c["media_type"] == "image"), "video": sum(1 for c in clips if c["media_type"] == "video")}
        self.say(f"  selection automatique : {len(clips)} souvenir(s) retenu(s) sur {event.guest_uploads.count()} ({kinds['image']} photo(s), {kinds['video']} video(s)), "
                 f"{len({c['category'] for c in clips})} moment(s) different(s)")
        self.verify("la selection est plus courte que le total (le film reste dense)", 0 < len(clips) < event.guest_uploads.count())
        self.verify("la duree du film respecte la limite du film heros", movie.duration is None or movie.duration.total_seconds() <= settings.MEMORA_MOVIE_MAX_DURATION_SECONDS)

        self.say("\n5) Livrables")
        self._inspect("film", movie.final_file, "hero")
        self.verify("teaser genere", bool(movie.teaser_file))
        if movie.teaser_file:
            self._inspect("teaser", movie.teaser_file, "teaser")
        self.verify("pas d'integrale (livrables = film + teaser)", not movie.full_file)
        self.verify("collecte fermee automatiquement a la fin du film", not Event.objects.get(pk=event.pk).is_active)

        self.say("\n6) Notification « film pret »")
        if self.options["email"]:
            self.verify("mail « film pret » envoye a l'organisateur", movie.organizer_notified_at is not None, str(movie.edit_decision_data.get("notification")))
        else:
            self.say("  (aucune adresse fournie : mail non teste)")

        self.say("\n7) Telechargement et pages, comme l'organisateur")
        host = next((h for h in settings.ALLOWED_HOSTS if h and h != "*" and not h.startswith(".")), "127.0.0.1")
        client = Client(HTTP_HOST=host)
        self.is_s3 = settings.MEMORA_STORAGE_BACKEND == "s3"
        client.force_login(event.organizer)
        for label, query in (("film", ""), ("teaser", "?v=teaser")):
            response = client.get(reverse("events:download_movie", kwargs={"pk": event.pk}) + query, secure=True)
            location = response.get("Location", "")
            self.verify(f"telechargement {label} : redirection vers un lien signe" if self.is_s3 else f"telechargement {label} : fichier servi (stockage local)",
                       (response.status_code == 302 and "Signature" in location) if self.is_s3 else response.status_code == 200, str(response.status_code))
            if location.startswith("http"):
                request = urllib.request.Request(location, headers={"Range": "bytes=0-1023"})
                try:
                    with urllib.request.urlopen(request, timeout=60) as remote:
                        disposition = remote.headers.get("Content-Disposition", "")
                        self.verify(f"telechargement {label} : le lien signe repond ({remote.status}) et force l'enregistrement", remote.status in (200, 206) and "attachment" in disposition, disposition)
                except Exception as exc:
                    self.verify(f"telechargement {label} : le lien signe repond", False, str(exc)[:160])
        for name, url in (("page du film (organisateur)", reverse("events:movie_ready", kwargs={"pk": event.pk})),
                          ("tableau de bord", reverse("events:detail", kwargs={"pk": event.pk})),
                          ("page publique du film", event.get_public_movie_url())):
            response = client.get(url, secure=True)
            self.verify(f"{name} : 200", response.status_code == 200, str(response.status_code))

        self.say("\n8) ZIP de tous les originaux (streaming, volume reel)")
        started = time.time()
        total = chunks = 0
        for chunk in iter_event_zip_chunks(event):
            total += len(chunk)
            chunks += 1
        peak = ""
        try:
            for line in Path("/proc/self/status").read_text().splitlines():
                if line.startswith("VmHWM"):
                    peak = f", pic memoire du process {int(line.split()[1]) / 1024:.0f} Mo"
        except OSError:
            pass
        self.say(f"  ZIP de {total / 1e6:.0f} Mo produit en {time.time() - started:.0f} s ({chunks} morceaux{peak})")
        self.verify("le ZIP contient tous les originaux (taille >= somme des fichiers)", total >= (event.guest_uploads.aggregate(t=Sum('file_size'))['t'] or 0) * 0.95)

    def _cleanup(self, event):
        self.say("\nNettoyage")
        if self.temp_names:
            self.say(f"  {len(self.temp_names)} planche(s)-contact conservee(s) sous rehearsal/ (quelques Ko, a supprimer quand vous voulez).")
        try:
            delete_event(event)
            bot = get_user_model().objects.filter(username=self.bot_username).first()
            if bot and not bot.events.exists():
                bot.delete()
            self.say("  evenement de test, fichiers et lignes supprimes.")
        except Exception as exc:
            self.say(f"  ! nettoyage incomplet : {type(exc).__name__}: {exc}")
