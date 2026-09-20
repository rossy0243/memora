"""Pipeline hybride du montage du livre d'or (cartons Remotion + assemblage FFmpeg).

Les tests d'encodage lancent le vrai FFmpeg (sur de tres petits clips) : ce qui
compte ici, ce sont les commandes construites — filtres, fondus, concat sans
reencodage, mixage —, qu'un mock ne validerait pas. Ignores si FFmpeg est absent.
"""
import json
import shutil
import subprocess
import tempfile
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from events.models import Event, EventType
from processing import guestbook_montage as gm

from .models import GuestBookMovie


def _binary_available(binary):
    return shutil.which(binary) is not None or Path(binary).exists()


FFMPEG_AVAILABLE = _binary_available(settings.MEMORA_FFMPEG_BINARY) and _binary_available(
    settings.MEMORA_FFPROBE_BINARY
)


def _ffmpeg(*args):
    subprocess.run(
        [settings.MEMORA_FFMPEG_BINARY, "-hide_banner", "-loglevel", "error", "-y", *args],
        check=True,
        capture_output=True,
    )


def _probe(path):
    result = subprocess.run(
        [
            settings.MEMORA_FFPROBE_BINARY, "-v", "error",
            "-show_entries", "format=duration:stream=codec_type,width,height",
            "-of", "json", str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    streams = payload["streams"]
    return {
        "duration": float(payload["format"]["duration"]),
        "video": next((s for s in streams if s["codec_type"] == "video"), None),
        "has_audio": any(s["codec_type"] == "audio" for s in streams),
    }


def _make_clip(path, *, size="320x240", seconds=2, audio=True):
    """Petit clip de test. mpeg4 : l'encodeur toujours present, meme dans un FFmpeg LGPL."""
    args = ["-f", "lavfi", "-i", f"testsrc=size={size}:rate=25:duration={seconds}"]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-c:a", "aac", "-shortest"]
    _ffmpeg(*args, "-c:v", "mpeg4", str(path))


def _make_card(path):
    _ffmpeg("-f", "lavfi", "-i", "color=c=0x181310:size=1920x1080", "-frames:v", "1", str(path))


class MusicGainExpressionTests(SimpleTestCase):
    def test_without_messages_the_bed_volume_is_constant(self):
        self.assertEqual(gm._music_gain_expression([], 0.12, 0.04), "0.1200")

    def test_one_dip_term_per_message_window(self):
        expression = gm._music_gain_expression([(5.0, 11.0), (14.0, 19.0), (22.0, 30.0)], 0.12, 0.04)

        self.assertEqual(expression.count("clip("), 3)
        self.assertTrue(expression.startswith("0.1200-0.0800*("))


class CardSpecTests(SimpleTestCase):
    def test_cards_are_rendered_when_animations_are_settled_and_before_the_exit(self):
        event = SimpleNamespace(title="Camille & Noé")
        messages = [SimpleNamespace(guest_name="  Tante Jeanne "), SimpleNamespace(guest_name="")]

        cards = gm._card_specs(event, messages, Path("/tmp/work"))

        self.assertEqual(cards["intro"]["props"]["title"], "Camille & Noé")
        self.assertEqual(cards["intro"]["props"]["subtitle"], "Livre d'or")
        self.assertEqual([c["props"]["name"] for c in cards["names"]], ["Tante Jeanne", ""])
        self.assertEqual(cards["outro"]["props"]["subtitle"], "Camille & Noé")
        for card in [cards["intro"], cards["outro"], *cards["names"]]:
            duration = card["props"]["durationInFrames"]
            # Entree terminee (> 40 images) mais sortie (14 dernieres images) pas commencee.
            self.assertGreater(card["frame"], 38)
            self.assertLess(card["frame"], duration - 14)


class RenderCardsTests(SimpleTestCase):
    def test_cards_are_rendered_in_one_node_call_with_progress(self):
        reported = []

        def fake_run(command, **kwargs):
            joined = " ".join(command)
            self.assertIn("render-cards.mjs", joined)
            self.assertIn("--cards=", joined)
            self.assertIn("--progress-file=", joined)
            self.assertEqual(kwargs["progress_callback"], reported.append)

        cards = {
            "intro": {"output": "a.png", "frame": 70, "props": {}},
            "names": [{"output": "n.png", "frame": 45, "props": {}}],
            "outro": {"output": "b.png", "frame": 80, "props": {}},
        }
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            gm.shutil, "which", return_value="/usr/bin/node"
        ), patch.object(gm, "run_remotion_subprocess", side_effect=fake_run) as run:
            gm._render_cards(cards, Path(tmp), Path(tmp), reported.append)

            specs = json.loads((Path(tmp) / "cards.json").read_text(encoding="utf-8"))
        run.assert_called_once()
        self.assertEqual([spec["output"] for spec in specs], ["a.png", "n.png", "b.png"])


@override_settings(MEMORA_GUESTBOOK_MAX_VIDEO_DURATION_SECONDS=20)
class FfmpegSegmentTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        if not FFMPEG_AVAILABLE:
            from unittest import SkipTest

            raise SkipTest("FFmpeg indisponible")
        super().setUpClass()

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="memora_gb_test_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.encoder = settings.MEMORA_MOVIE_VIDEO_ENCODER

    def _segment(self, source, name="seg.mp4", fallback=2):
        destination = self.tmp / name
        duration = gm._encode_message_segment(
            source, destination,
            fallback_seconds=fallback, grade=gm._grade_filter(None), encoder=self.encoder, threads=1,
        )
        return destination, duration

    def test_landscape_message_becomes_a_1080p_segment_with_sound(self):
        clip = self.tmp / "land.mp4"
        _make_clip(clip, size="640x360", seconds=2)

        segment, duration = self._segment(clip)

        info = _probe(segment)
        self.assertEqual((info["video"]["width"], info["video"]["height"]), (1920, 1080))
        self.assertTrue(info["has_audio"])
        self.assertAlmostEqual(duration, 2.0, delta=0.3)

    def test_portrait_message_is_framed_on_a_blurred_background_not_cropped(self):
        clip = self.tmp / "port.mp4"
        _make_clip(clip, size="240x426", seconds=2)

        segment, _ = self._segment(clip)

        info = _probe(segment)
        self.assertEqual((info["video"]["width"], info["video"]["height"]), (1920, 1080))

    def test_silent_message_gets_a_silent_track_so_the_concat_stays_uniform(self):
        clip = self.tmp / "silent.mp4"
        _make_clip(clip, seconds=2, audio=False)

        segment, duration = self._segment(clip)

        self.assertTrue(_probe(segment)["has_audio"])
        self.assertAlmostEqual(duration, 2.0, delta=0.3)

    def test_message_longer_than_the_ceiling_is_capped(self):
        clip = self.tmp / "long.mp4"
        _make_clip(clip, seconds=3)

        with override_settings(MEMORA_GUESTBOOK_MAX_VIDEO_DURATION_SECONDS=1):
            segment, duration = self._segment(clip)

        self.assertLessEqual(duration, 2.2)  # plafond = 2 x duree maximale d'enregistrement

    def test_webm_recorded_like_mediarecorder_is_measured_even_without_a_duration_header(self):
        """Les messages du stand sont des webm VP9 ecrits en flux par MediaRecorder :
        ni duree ni index dans l'en-tete (ffprobe repond N/A). La duree doit alors
        venir des paquets, sinon fondus et musique seraient calees a l'aveugle."""
        clip = self.tmp / "stream.webm"
        try:
            with open(clip, "wb") as target:
                subprocess.run(
                    [
                        settings.MEMORA_FFMPEG_BINARY, "-hide_banner", "-loglevel", "error", "-y",
                        "-f", "lavfi", "-i", "testsrc=size=160x284:rate=47:duration=3",
                        "-f", "lavfi", "-i", "sine=frequency=300:duration=3",
                        "-c:v", "libvpx", "-b:v", "500k", "-c:a", "libopus", "-shortest",
                        "-f", "webm", "pipe:1",
                    ],
                    check=True, stdout=target, stderr=subprocess.PIPE,
                )
        except subprocess.CalledProcessError:
            self.skipTest("encodeur VP8/Opus indisponible")
        header = subprocess.run(
            [settings.MEMORA_FFPROBE_BINARY, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(clip)],
            capture_output=True, text=True,
        ).stdout.strip()
        self.assertIn(header, ("N/A", ""), "le fichier de test doit bien etre sans duree d'en-tete")

        self.assertAlmostEqual(gm._probe_duration(clip), 3.0, delta=0.2)
        _, duration = self._segment(clip, fallback=10)
        self.assertAlmostEqual(duration, 3.0, delta=0.3)

    def test_card_becomes_a_silent_segment_of_the_requested_length(self):
        card = self.tmp / "card.png"
        _make_card(card)
        destination = self.tmp / "card.mp4"

        duration = gm._encode_card_segment(card, destination, seconds=2, encoder=self.encoder, threads=1)

        info = _probe(destination)
        self.assertEqual((info["video"]["width"], info["video"]["height"]), (1920, 1080))
        self.assertAlmostEqual(duration, 2.0, delta=0.3)

    def test_failing_ffmpeg_raises_with_the_error_text(self):
        with self.assertRaises(gm.MontageError) as context:
            self._segment(self.tmp / "absent.mp4")

        self.assertIn("FFmpeg", str(context.exception))

    def test_assembly_concatenates_without_music_and_mixes_music_when_given(self):
        card = self.tmp / "card.png"
        _make_card(card)
        segments = []
        for index in range(2):
            clip = self.tmp / f"m{index}.mp4"
            _make_clip(clip, seconds=2)
            message_segment, _ = self._segment(clip, name=f"msg{index}.mp4")
            card_segment = self.tmp / f"card{index}.mp4"
            gm._encode_card_segment(card, card_segment, seconds=1, encoder=self.encoder, threads=1)
            segments += [card_segment, message_segment]

        plain = self.tmp / "plain.mp4"
        gm._assemble(segments, [], 6.0, None, 0, plain, self.tmp, None)
        self.assertAlmostEqual(_probe(plain)["duration"], 6.0, delta=0.5)

        music = self.tmp / "music.wav"
        _ffmpeg("-f", "lavfi", "-i", "anoisesrc=color=pink:amplitude=0.3:duration=3", str(music))
        mixed = self.tmp / "mixed.mp4"
        seen = []
        gm._assemble(
            segments, [(1.0, 3.0), (4.0, 6.0)], 6.0, music, 0.2, mixed, self.tmp, seen.append
        )

        info = _probe(mixed)
        self.assertTrue(info["has_audio"])
        # Musique plus courte que le montage : elle est rebouclee, jamais le montage tronque.
        self.assertAlmostEqual(info["duration"], 6.0, delta=0.5)
        self.assertTrue(seen)
        self.assertLessEqual(max(seen), 1.0)

    def test_light_version_is_720p(self):
        clip = self.tmp / "m.mp4"
        _make_clip(clip, size="640x360", seconds=2)
        segment, _ = self._segment(clip)
        light = self.tmp / "light.mp4"

        gm._encode_light_version(segment, light, 2.0, None)

        self.assertEqual(_probe(light)["video"]["height"], 720)


@override_settings(
    MEMORA_GUESTBOOK_MONTAGE_INTRO_CARD_SECONDS=1,
    MEMORA_GUESTBOOK_MONTAGE_NAME_CARD_SECONDS=1,
    MEMORA_GUESTBOOK_MONTAGE_OUTRO_CARD_SECONDS=1,
    MEMORA_GUESTBOOK_MAX_VIDEO_DURATION_SECONDS=20,
)
class RenderGuestbookMontageTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        if not FFMPEG_AVAILABLE:
            from unittest import SkipTest

            raise SkipTest("FFmpeg indisponible")
        super().setUpClass()

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="memora_gb_e2e_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.event = SimpleNamespace(pk=1, slug="test", title="Camille & Noé")
        self.messages = []
        for index, name in enumerate(["Les voisins", "", "Tata Jeanne"]):
            clip = self.tmp / f"src{index}.mp4"
            _make_clip(clip, seconds=2, audio=index != 1)
            self.messages.append(
                SimpleNamespace(
                    original_filename=clip.name,
                    media_file=SimpleNamespace(name=clip.name),
                    duration=timedelta(seconds=2),
                    guest_name=name,
                )
            )

    def _fake_cards(self, cards, work_dir, assets_dir, callback):
        for card in [cards["intro"], *cards["names"], cards["outro"]]:
            _make_card(Path(card["output"]))
        callback(1.0)

    def _render(self, **kwargs):
        def materialize(message, destination):
            shutil.copy(self.tmp / message.original_filename, destination)

        sound = SimpleNamespace(has_track=False, mood="warm_lounge", first_beat_offset=0.0)
        with patch.object(gm, "_materialize_upload", materialize), patch.object(
            gm, "choose_movie_soundtrack", return_value=sound
        ), patch.object(gm, "_render_cards", self._fake_cards):
            return gm.render_guestbook_montage(
                self.event, self.messages, self.tmp / "hd.mp4", self.tmp / "light.mp4", **kwargs
            )

    def test_montage_follows_intro_then_card_and_message_per_guest_then_outro(self):
        progress = []

        result = self._render(progress_callback=lambda fraction, message: progress.append((fraction, message)))

        # intro 1 s + 3 x (carton 1 s + message 2 s) + fin 1 s = 11 s
        self.assertAlmostEqual(result.duration_seconds, 11.0, delta=1.0)
        info = _probe(result.output_path)
        self.assertAlmostEqual(info["duration"], 11.0, delta=1.0)
        self.assertEqual((info["video"]["width"], info["video"]["height"]), (1920, 1080))
        self.assertEqual(_probe(result.light_path)["video"]["height"], 720)

        fractions = [fraction for fraction, _ in progress]
        self.assertEqual(fractions, sorted(fractions), "la progression ne doit jamais reculer")
        self.assertGreaterEqual(fractions[-1], 0.99)
        texts = " ".join(message for _, message in progress)
        for step in ("Préparation des messages", "cartons", "Montage des messages (3/3)", "Assemblage", "légère"):
            self.assertIn(step, texts)

    def test_a_failing_light_version_never_costs_the_hd_montage(self):
        with patch.object(gm, "_encode_light_version", side_effect=gm.MontageError("boom")):
            result = self._render()

        self.assertTrue(result.output_path.exists())
        self.assertIsNone(result.light_path)
        self.assertFalse((self.tmp / "light.mp4").exists())

    def test_a_failing_segment_aborts_the_montage(self):
        with patch.object(gm, "_encode_message_segment", side_effect=gm.MontageError("segment KO")):
            with self.assertRaises(gm.MontageError):
                self._render()

    def test_no_messages_is_refused(self):
        with self.assertRaises(ValueError):
            gm.render_guestbook_montage(self.event, [], self.tmp / "hd.mp4")


class ProcessGuestbookMovieStorageTests(TestCase):
    def setUp(self):
        self.organizer = get_user_model().objects.create_user(username="orga-p", password="secret")
        self.event = Event.objects.create(
            organizer=self.organizer,
            title="Mariage Process",
            event_type=EventType.objects.get(code="wedding"),
            event_date=date(2026, 7, 8),
        )
        from .models import GuestBookMessage

        GuestBookMessage.objects.create(
            event=self.event, guest_name="Les voisins", media_file="events/x/m.mp4",
            original_filename="m.mp4", file_size=10,
        )
        self.media_root = tempfile.mkdtemp(prefix="memora_gb_media_")
        self.addCleanup(shutil.rmtree, self.media_root, ignore_errors=True)

    def _process(self, movie, *, with_light=True):
        from processing.guestbook_montage import process_guestbook_movie

        render = lambda event, messages, out, light_output_path=None, progress_callback=None: gm_write(out, light_output_path, with_light)
        with override_settings(MEDIA_ROOT=self.media_root), patch(
            "processing.guestbook_montage.render_guestbook_montage", side_effect=render
        ), patch("processing.guestbook_montage.shutil.which", return_value="/usr/bin/ffmpeg"):
            return process_guestbook_movie(movie)

    def test_completed_montage_stores_both_files_with_their_sizes(self):
        movie = GuestBookMovie.objects.create(event=self.event)

        self._process(movie)

        movie.refresh_from_db()
        self.assertEqual(movie.status, GuestBookMovie.Status.COMPLETED)
        self.assertTrue(movie.final_file)
        self.assertTrue(movie.light_file)
        self.assertEqual(movie.final_size, len(b"fake-hd-bytes"))
        self.assertEqual(movie.light_size, len(b"fake-light"))
        self.assertEqual(movie.duration, timedelta(seconds=42))
        self.assertEqual(movie.render_provider, "remotion+ffmpeg")

    def test_missing_light_version_leaves_only_the_hd_file(self):
        movie = GuestBookMovie.objects.create(event=self.event)

        self._process(movie, with_light=False)

        movie.refresh_from_db()
        self.assertEqual(movie.status, GuestBookMovie.Status.COMPLETED)
        self.assertTrue(movie.final_file)
        self.assertFalse(movie.light_file)
        self.assertIsNone(movie.light_size)

    def test_regenerating_replaces_the_previous_files_instead_of_orphaning_them(self):
        movie = GuestBookMovie.objects.create(event=self.event)
        self._process(movie)
        movie.refresh_from_db()
        first_hd, first_light = movie.final_file.name, movie.light_file.name
        storage = movie.final_file.storage
        movie.status = GuestBookMovie.Status.PENDING
        movie.save(update_fields=["status"])

        self._process(movie)

        movie.refresh_from_db()
        self.assertNotEqual(movie.final_file.name, first_hd)
        with override_settings(MEDIA_ROOT=self.media_root):
            self.assertFalse(storage.exists(first_hd))
            self.assertFalse(storage.exists(first_light))
            self.assertTrue(storage.exists(movie.final_file.name))

    def test_failed_render_keeps_the_previous_montage_and_records_the_error(self):
        movie = GuestBookMovie.objects.create(event=self.event)
        self._process(movie)
        movie.refresh_from_db()
        previous = movie.final_file.name
        movie.status = GuestBookMovie.Status.PENDING
        movie.save(update_fields=["status"])

        from processing.guestbook_montage import MontageError, process_guestbook_movie

        with override_settings(MEDIA_ROOT=self.media_root), patch(
            "processing.guestbook_montage.render_guestbook_montage", side_effect=MontageError("FFmpeg KO")
        ), patch("processing.guestbook_montage.shutil.which", return_value="/usr/bin/ffmpeg"):
            process_guestbook_movie(movie)

        movie.refresh_from_db()
        self.assertEqual(movie.status, GuestBookMovie.Status.FAILED)
        self.assertIn("FFmpeg KO", movie.error_message)
        self.assertEqual(movie.final_file.name, previous)


def gm_write(output_path, light_output_path, with_light):
    from .tests import _write_montage_files

    return _write_montage_files(output_path, light_output_path, with_light=with_light)


class GuestbookDownloadTests(TestCase):
    def setUp(self):
        self.organizer = get_user_model().objects.create_user(username="orga-d", password="secret")
        self.event = Event.objects.create(
            organizer=self.organizer,
            title="Mariage Telechargement",
            couple_name="Lea & Sam",
            event_type=EventType.objects.get(code="wedding"),
            event_date=date(2026, 7, 8),
        )
        self.media_root = tempfile.mkdtemp(prefix="memora_gb_dl_")
        self.addCleanup(shutil.rmtree, self.media_root, ignore_errors=True)
        with override_settings(MEDIA_ROOT=self.media_root):
            self.movie = GuestBookMovie.objects.create(event=self.event, status=GuestBookMovie.Status.COMPLETED)
            self.movie.final_file.save("hd.mp4", ContentFile(b"HD-CONTENT"), save=False)
            self.movie.light_file.save("light.mp4", ContentFile(b"LIGHT"), save=False)
            self.movie.save()
        self.url = reverse("events:download_guestbook_movie", kwargs={"pk": self.event.pk})

    def test_hd_is_served_as_an_attachment_by_default(self):
        self.client.login(username="orga-d", password="secret")

        with override_settings(MEDIA_ROOT=self.media_root):
            response = self.client.get(self.url)
            body = b"".join(response.streaming_content)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(body, b"HD-CONTENT")
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertIn("memora-livre-dor-lea-sam.mp4", response["Content-Disposition"])

    def test_light_version_is_served_on_request(self):
        self.client.login(username="orga-d", password="secret")

        with override_settings(MEDIA_ROOT=self.media_root):
            response = self.client.get(self.url, {"v": "light"})
            body = b"".join(response.streaming_content)

        self.assertEqual(body, b"LIGHT")
        self.assertIn("leger", response["Content-Disposition"])

    def test_other_organizers_cannot_download(self):
        get_user_model().objects.create_user(username="intrus", password="secret")
        self.client.login(username="intrus", password="secret")

        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_not_ready_montage_is_a_404(self):
        GuestBookMovie.objects.filter(pk=self.movie.pk).update(status=GuestBookMovie.Status.PROCESSING)
        self.client.login(username="orga-d", password="secret")

        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_on_r2_the_browser_is_redirected_to_a_signed_url_forcing_the_download(self):
        """Pas de flux a travers Django : l'URL signee de R2 impose `attachment`,
        ce qu'un simple <a download> cross-origin ne sait pas faire."""
        from storages.backends.s3 import S3Storage

        captured = {}

        class FakeS3(S3Storage):
            def __init__(self):
                pass

            def url(self, name, parameters=None, expire=None, http_method=None):
                captured.update(name=name, parameters=parameters, expire=expire)
                return "https://r2.example/signed?X-Amz-Signature=abc"

        self.client.login(username="orga-d", password="secret")
        with patch.object(GuestBookMovie._meta.get_field("final_file"), "storage", FakeS3()):
            response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "https://r2.example/signed?X-Amz-Signature=abc")
        self.assertIn("no-store", response["Cache-Control"])
        self.assertIn("attachment", captured["parameters"]["ResponseContentDisposition"])
        self.assertEqual(captured["parameters"]["ResponseContentType"], "video/mp4")
        self.assertLessEqual(captured["expire"], 3600)

    def test_panel_offers_both_versions_with_their_size(self):
        GuestBookMovie.objects.filter(pk=self.movie.pk).update(final_size=850 * 1024 * 1024, light_size=340 * 1024 * 1024)
        self.client.login(username="orga-d", password="secret")

        with override_settings(MEDIA_ROOT=self.media_root):
            response = self.client.get(reverse("events:guestbook_messages", kwargs={"pk": self.event.pk}))

        self.assertContains(response, "Télécharger en HD (850")
        self.assertContains(response, "Version légère (340")
        self.assertContains(response, f"{self.url}?v=light")


class PurgeOrphanGuestbookFilesTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp(prefix="memora_gb_orphans_")
        self.addCleanup(shutil.rmtree, self.media_root, ignore_errors=True)
        organizer = get_user_model().objects.create_user(username="orga-o", password="secret")
        self.event = Event.objects.create(
            organizer=organizer,
            title="Mariage Orphelins",
            event_type=EventType.objects.get(code="wedding"),
            event_date=date(2026, 7, 8),
        )
        self.directory = Path(self.media_root) / "events" / self.event.slug / "livre-dor" / "montage"
        self.directory.mkdir(parents=True)
        for name in ("livre-dor-x.mp4", "livre-dor-x-leger.mp4", "livre-dor-x_OLD1.mp4", "livre-dor-x-leger_OLD2.mp4", "notes.txt"):
            (self.directory / name).write_bytes(b"data")
        base = f"events/{self.event.slug}/livre-dor/montage"
        self.movie = GuestBookMovie.objects.create(
            event=self.event, status=GuestBookMovie.Status.COMPLETED,
            final_file=f"{base}/livre-dor-x.mp4", light_file=f"{base}/livre-dor-x-leger.mp4",
        )

    def _run(self, *args):
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        with override_settings(MEDIA_ROOT=self.media_root):
            call_command("purge_orphan_guestbook_files", *args, stdout=out)
        return out.getvalue()

    def _files(self):
        return sorted(p.name for p in self.directory.iterdir())

    def test_dry_run_lists_orphans_but_deletes_nothing(self):
        output = self._run()

        self.assertIn("livre-dor-x_OLD1.mp4", output)
        self.assertIn("2 fichier(s) orphelin(s)", output)
        self.assertEqual(len(self._files()), 5)

    def test_apply_removes_only_unreferenced_montage_files(self):
        self._run("--apply")

        self.assertEqual(self._files(), ["livre-dor-x-leger.mp4", "livre-dor-x.mp4", "notes.txt"])

    def test_montage_in_progress_is_left_alone(self):
        GuestBookMovie.objects.filter(pk=self.movie.pk).update(status=GuestBookMovie.Status.PROCESSING)

        self._run("--apply")

        self.assertEqual(len(self._files()), 5)
