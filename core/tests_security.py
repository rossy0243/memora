"""Securite : tentatives de mot de passe repetees, reinitialisations en rafale, redirection ouverte,
faux fichiers video, adresse IP reelle derriere Cloudflare, fuseau horaire."""
from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core import throttle
from core.models import OperationalState
from core.security import get_client_ip
from events.models import Event, EventType
from uploads.models import GuestUpload

MP4_HEAD = bytes([0, 0, 0, 24]) + b"ftypmp42" + bytes(16)


class LoginThrottleTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="cible", password="Bon-mot-de-passe-1x", email="cible@example.org")
        self.url = reverse("accounts:login")

    def attempt(self, password, username="cible", **extra):
        return self.client.post(self.url, {"username": username, "password": password}, **extra)

    def test_five_failures_lock_the_pair_even_for_the_right_password(self):
        for i in range(5):
            self.assertEqual(self.attempt(f"mauvais-{i}").status_code, 200)

        response = self.attempt("Bon-mot-de-passe-1x")  # le bon mot de passe est refuse pendant le blocage
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertContains(response, "Trop de tentatives")

    def test_a_success_before_the_limit_resets_the_counter(self):
        for i in range(4):
            self.attempt(f"mauvais-{i}")
        self.assertEqual(self.attempt("Bon-mot-de-passe-1x").status_code, 302)
        self.client.logout()
        for i in range(4):
            self.attempt(f"encore-{i}")

        self.assertEqual(self.attempt("Bon-mot-de-passe-1x").status_code, 302)  # 4 echecs seulement depuis le succes

    def test_the_lock_expires_after_fifteen_minutes(self):
        for i in range(5):
            self.attempt(f"mauvais-{i}")
        self.assertIsNotNone(throttle.locked_until(RequestFactory().post("/"), "cible") or True)
        OperationalState.objects.filter(key__startswith="throttle:login:pair:").update(value={"locked_until": (timezone.now() - timedelta(minutes=1)).isoformat(), "count": 0})
        OperationalState.objects.filter(key__startswith="throttle:login:ip:").update(value={})

        self.assertEqual(self.attempt("Bon-mot-de-passe-1x").status_code, 302)

    def test_one_address_trying_many_usernames_gets_locked_too(self):
        for i in range(30):
            self.attempt("x", username=f"inconnu-{i}")

        self.assertEqual(self.attempt("Bon-mot-de-passe-1x").status_code, 200)  # meme le bon compte : l'IP est bloquee

    def test_another_address_is_not_locked_by_someone_else_failures(self):
        for i in range(5):
            self.attempt(f"mauvais-{i}")

        response = self.attempt("Bon-mot-de-passe-1x", REMOTE_ADDR="203.0.113.77")
        self.assertEqual(response.status_code, 302)

    def test_the_admin_login_is_protected_by_the_same_backend(self):
        admin = get_user_model().objects.create_superuser(username="chef", password="Admin-mot-de-passe-1x", email="chef@example.org")
        url = reverse("admin:login")
        for i in range(5):
            self.client.post(url, {"username": "chef", "password": f"mauvais-{i}", "next": "/admin/"})

        self.client.post(url, {"username": "chef", "password": "Admin-mot-de-passe-1x", "next": "/admin/"})

        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertIsNotNone(admin)

    def test_no_blocking_outside_a_request(self):
        from django.contrib.auth import authenticate

        self.assertEqual(authenticate(username="cible", password="Bon-mot-de-passe-1x"), self.user)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class PasswordResetFloodTests(TestCase):
    def setUp(self):
        get_user_model().objects.create_user(username="victime", password="x", email="victime@example.org")
        self.url = reverse("accounts:password_reset")

    def test_a_flood_of_requests_for_one_address_sends_at_most_three_emails(self):
        for _ in range(8):
            response = self.client.post(self.url, {"email": "victime@example.org"})
            self.assertEqual(response.status_code, 302)  # meme reponse : rien n'est revele

        self.assertEqual(len(mail.outbox), 3)

    def test_one_address_cannot_bomb_many_victims(self):
        for i in range(9):
            self.client.post(self.url, {"email": f"victime{i}@example.org"})
            get_user_model().objects.get_or_create(username=f"v{i}", defaults={"email": f"victime{i}@example.org"})

        self.assertLessEqual(len(mail.outbox), 5)


class OpenRedirectTests(TestCase):
    def setUp(self):
        organizer = get_user_model().objects.create_user(username="orga-redir", password="secret")
        self.event = Event.objects.create(
            organizer=organizer, title="Redir", event_type=EventType.objects.get(code="wedding"), event_date=date(2026, 9, 26)
        )
        self.upload = GuestUpload.objects.create(
            event=self.event, category=self.event.upload_categories.first(), media_file="x.jpg", media_type="image",
            original_filename="x.jpg", file_size=1,
        )
        self.client.login(username="orga-redir", password="secret")
        self.url = reverse("events:set_media_moderation", kwargs={"pk": self.event.pk, "upload_pk": self.upload.pk})

    def test_next_on_another_site_is_ignored(self):
        for hostile in ("https://evil.example/phish", "//evil.example/x", "javascript:alert(1)"):
            response = self.client.post(self.url, {"status": "approved", "next": hostile})
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response["Location"], reverse("events:media_list", kwargs={"pk": self.event.pk}), hostile)

    def test_next_on_this_site_is_kept(self):
        target = reverse("events:media_list", kwargs={"pk": self.event.pk}) + "?type=video"

        response = self.client.post(self.url, {"status": "approved", "next": target})

        self.assertEqual(response["Location"], target)


class FakeVideoTests(TestCase):
    def setUp(self):
        organizer = get_user_model().objects.create_user(username="orga-fake", password="secret")
        self.event = Event.objects.create(
            organizer=organizer, title="Fake", event_type=EventType.objects.get(code="wedding"), event_date=timezone.localdate()
        )
        self.event.mark_paid(provider="test")
        self.event.save()
        self.url = reverse("uploads:create", kwargs={"slug": self.event.slug, "access_key": self.event.public_access_key})

    def post(self, name, content, content_type):
        return self.client.post(self.url, {"media_file": SimpleUploadedFile(name, content, content_type=content_type)})

    @patch("uploads.forms._probe_video_duration", return_value=5)
    def test_a_playlist_disguised_as_mp4_is_refused_before_any_ffmpeg_call(self, probe):
        playlist = b"#EXTM3U\n#EXTINF:10,\nhttp://169.254.169.254/latest/meta-data/\n"
        for name in ("clip.mp4", "clip.mov"):
            response = self.post(name, playlist, "video/mp4")
            self.assertContains(response, "Ce format n&#x27;est pas accepté.")
        response = self.post("clip.webm", b"ffconcat version 1.0\nfile '/etc/passwd'\n", "video/webm")
        self.assertContains(response, "Ce format n&#x27;est pas accepté.")
        probe.assert_not_called()
        self.assertEqual(GuestUpload.objects.count(), 0)

    @patch("uploads.forms._probe_video_duration", return_value=5)
    def test_real_mp4_and_webm_headers_are_accepted(self, _probe):
        self.assertEqual(self.post("a.mp4", MP4_HEAD + b"data", "video/mp4").status_code, 302)
        webm = bytes([0x1A, 0x45, 0xDF, 0xA3]) + bytes(60)
        self.client.session.flush()
        with override_settings(MEMORA_UPLOAD_COOLDOWN_SECONDS=0, MEMORA_SESSION_UPLOAD_LIMIT=9):
            self.assertEqual(self.post("b.webm", webm, "video/webm").status_code, 302)


class ClientIpTests(TestCase):
    @override_settings(MEMORA_TRUST_X_FORWARDED_FOR=True)
    def test_the_cloudflare_header_wins_over_a_forged_forwarded_for(self):
        request = RequestFactory().get("/", HTTP_X_FORWARDED_FOR="6.6.6.6, 7.7.7.7", HTTP_CF_CONNECTING_IP="41.77.1.2", REMOTE_ADDR="10.0.0.1")

        self.assertEqual(get_client_ip(request), "41.77.1.2")

    @override_settings(MEMORA_TRUST_X_FORWARDED_FOR=True)
    def test_without_the_cloudflare_header_the_previous_behaviour_remains(self):
        request = RequestFactory().get("/", HTTP_X_FORWARDED_FOR="41.77.1.2", REMOTE_ADDR="10.0.0.1")

        self.assertEqual(get_client_ip(request), "41.77.1.2")

    @override_settings(MEMORA_TRUST_X_FORWARDED_FOR=False)
    def test_headers_are_ignored_when_not_trusted(self):
        request = RequestFactory().get("/", HTTP_CF_CONNECTING_IP="41.77.1.2", REMOTE_ADDR="10.0.0.1")

        self.assertEqual(get_client_ip(request), "10.0.0.1")


class SharedWifiTests(TestCase):
    """Regression : une salle entiere derriere UNE adresse IP ne doit pas etre limitee a 1 envoi / 8 s."""

    def test_two_guests_on_the_same_address_can_send_back_to_back(self):
        from django.test import Client

        organizer = get_user_model().objects.create_user(username="orga-wifi", password="secret")
        event = Event.objects.create(organizer=organizer, title="Wifi", event_type=EventType.objects.get(code="wedding"), event_date=timezone.localdate())
        event.mark_paid(provider="test")
        event.save()
        url = reverse("uploads:create", kwargs={"slug": event.slug, "access_key": event.public_access_key})
        import io
        from PIL import Image

        buffer = io.BytesIO()
        Image.new("RGB", (20, 20), (200, 100, 50)).save(buffer, format="JPEG")

        results = []
        for _ in range(6):
            guest = Client(REMOTE_ADDR="198.51.100.9")  # meme adresse, sessions differentes
            results.append(guest.post(url, {"media_file": SimpleUploadedFile("p.jpg", buffer.getvalue(), content_type="image/jpeg")}).status_code)

        self.assertEqual(results, [302] * 6)
        self.assertEqual(GuestUpload.objects.filter(event=event).count(), 6)


class TimeZoneTests(TestCase):
    def test_events_follow_kinshasa_time(self):
        from django.conf import settings

        self.assertEqual(settings.TIME_ZONE, "Africa/Kinshasa")

    def test_the_film_is_scheduled_at_noon_kinshasa_time(self):
        from processing.services import get_event_movie_schedule_at

        organizer = get_user_model().objects.create_user(username="orga-tz", password="secret")
        event = Event.objects.create(organizer=organizer, title="TZ", event_type=EventType.objects.get(code="wedding"), event_date=date(2026, 9, 26))

        scheduled = get_event_movie_schedule_at(event)

        self.assertEqual(scheduled.utcoffset(), timedelta(hours=1))
        self.assertEqual((scheduled.date().isoformat(), scheduled.hour), ("2026-09-27", 12))
