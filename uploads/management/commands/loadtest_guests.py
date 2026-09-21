"""Test de charge du parcours invite : des dizaines d'invites simules qui envoient leurs souvenirs.

    python manage.py loadtest_guests --base-url https://memoracd.site --scenarios A,B,C

A  invites avec des adresses IP differentes, debits mixtes (Wi-Fi, 4G, reseau lent), etalement realiste
B  tous les invites derriere UNE MEME adresse IP (Wi-Fi de la salle, ou reseau mobile partage)
C  pic : tous les invites envoient une video de 10 s en meme temps (le moment du toast)

Chaque scenario cree son propre evenement de test (mode test invites, sans formule : quota du site),
fait de vraies requetes HTTP (page d'entree, formulaire, envoi multipart avec cookie de session et
jeton CSRF, comme le navigateur), limite le debit de chaque invite (montee lente d'un telephone), puis
supprime l'evenement et ses fichiers. Une sonde mesure en continu la reactivite de la page d'un
NOUVEL invite qui scanne le QR pendant que les autres envoient.

A lancer depuis un serveur Render (bande passante propre), jamais depuis un evenement reel.
"""
import http.client
import random
import re
import secrets
import statistics
import threading
import time
import urllib.parse
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from events.models import Event, EventPlan, EventType
from events.services import delete_event
from processing.management.commands.rehearse_movie_pipeline import _encoders, _make_photo, _make_video

BOT_USERNAME = "loadtest-bot"
ERROR_PATTERNS = (
    ("cooldown", "Patientez quelques secondes"),
    ("ip_limit", "Trop d'envois depuis cette connexion"),
    ("session_limit", "atteint la limite de"),
    ("event_quota", "atteint le nombre de souvenirs"),
    ("format", "n'est pas accepté"),
)
BANDWIDTH_MIX = ((0.60, 20.0), (0.30, 5.0), (0.10, 1.5))  # (part des invites, Mbit/s montants)


def _percentile(values, pct):
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(pct / 100 * (len(ordered) - 1))))]


class Guest(threading.Thread):
    """Un invite : entre par le QR, ouvre le formulaire, envoie N souvenirs avec des pauses."""

    def __init__(self, ident, run):
        super().__init__(daemon=True)
        self.number, self.run_ctx = ident, run
        rng = random.Random(run.seed * 1000 + ident)
        self.rng = rng
        roll, cumulative = rng.random(), 0.0
        self.mbps = BANDWIDTH_MIX[-1][1]
        for share, mbps in BANDWIDTH_MIX:
            cumulative += share
            if roll <= cumulative:
                self.mbps = mbps
                break
        self.cookies = {}
        self.fake_ip = f"198.51.{rng.randint(1, 254)}.{rng.randint(1, 254)}" if run.distinct_ips else ""
        self.conn = None

    # -- HTTP minimal, avec cookies et connexion persistante -------------------------------
    def _connect(self):
        parsed = self.run_ctx.parsed
        cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
        self.conn = cls(parsed.hostname, parsed.port, timeout=180)

    def _headers(self, extra=None):
        headers = {"Host": self.run_ctx.parsed.netloc, "User-Agent": "MemoraLoadTest/1.0 (iPhone)", "Accept": "text/html,*/*"}
        if self.fake_ip:
            headers["X-Forwarded-For"] = self.fake_ip
        if self.cookies:
            headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        headers.update(extra or {})
        return headers

    def _remember_cookies(self, response):
        for name, value in response.getheaders():
            if name.lower() == "set-cookie":
                pair = value.split(";", 1)[0]
                if "=" in pair:
                    key, val = pair.split("=", 1)
                    self.cookies[key.strip()] = val.strip()

    def get(self, path):
        if self.conn is None:
            self._connect()
        started = time.time()
        try:
            self.conn.request("GET", path, headers=self._headers())
            response = self.conn.getresponse()
            body = response.read().decode("utf-8", "replace")
        except (OSError, http.client.HTTPException):
            self.conn = None
            raise
        self._remember_cookies(response)
        return response.status, body, time.time() - started, response.getheader("Location", "")

    def post_multipart(self, path, fields, filename, content_type, data):
        boundary = "----memora" + secrets.token_hex(8)
        prefix = b"".join(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in fields.items()
        ) + f'--{boundary}\r\nContent-Disposition: form-data; name="media_file"; filename="{filename}"\r\nContent-Type: {content_type}\r\n\r\n'.encode()
        tail = f"\r\n--{boundary}--\r\n".encode()
        total = len(prefix) + len(data) + len(tail)
        if self.conn is None:
            self._connect()
        origin = f"{self.run_ctx.parsed.scheme}://{self.run_ctx.parsed.netloc}"
        headers = self._headers({
            "Content-Type": f"multipart/form-data; boundary={boundary}", "Content-Length": str(total),
            "X-Requested-With": "XMLHttpRequest", "Origin": origin, "Referer": origin + self.run_ctx.form_path,
        })
        try:
            self.conn.putrequest("POST", path, skip_host=True, skip_accept_encoding=True)
            for key, value in headers.items():
                self.conn.putheader(key, value)
            self.conn.endheaders()
            started = time.time()
            sent, bytes_per_second = 0, self.mbps * 1e6 / 8
            for blob in (prefix, data, tail):
                for offset in range(0, len(blob), 32 * 1024):
                    chunk = blob[offset:offset + 32 * 1024]
                    self.conn.send(chunk)
                    sent += len(chunk)
                    ahead = sent / bytes_per_second - (time.time() - started)  # debit montant limite du telephone
                    if ahead > 0:
                        time.sleep(ahead)
            upload_done = time.time()
            response = self.conn.getresponse()
            body = response.read().decode("utf-8", "replace")
        except (OSError, http.client.HTTPException):
            self.conn = None
            raise
        finished = time.time()
        self._remember_cookies(response)
        return response.status, body, upload_done - started, finished - upload_done, response.getheader("Location", "")

    # -- comportement -----------------------------------------------------------------------------
    def run(self):
        ctx = self.run_ctx
        time.sleep(ctx.ramp_seconds * self.number / max(ctx.guests, 1))
        try:
            status, _, elapsed, location = self.get(ctx.entry_path)
            ctx.record("page", "entree", status < 400, elapsed)
            status, body, elapsed, _ = self.get(ctx.form_path)
            ctx.record("page", "formulaire", status == 200, elapsed)
            match = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', body)
            token = match.group(1) if match else self.cookies.get("csrftoken", "")
        except Exception as exc:  # noqa: BLE001
            ctx.record("page", "entree", False, 0, error=f"{type(exc).__name__}")
            return

        for number in range(ctx.per_guest):
            if number:
                time.sleep(self.rng.uniform(*ctx.think))
            is_video = self.rng.random() < ctx.video_share
            kind, name, content_type, data = self.rng.choice(ctx.videos if is_video else ctx.photos)
            self._send_with_retries(token, kind, name, content_type, data)

    def _send_with_retries(self, token, kind, name, content_type, data):
        ctx = self.run_ctx
        for attempt in range(1, ctx.max_attempts + 1):
            try:
                status, body, upload_seconds, wait_seconds, location = self.post_multipart(
                    ctx.form_path, {"csrfmiddlewaretoken": token, "client_duration_seconds": "10" if kind == "video" else ""},
                    name, content_type, data,
                )
            except Exception as exc:  # noqa: BLE001
                ctx.record(kind, "envoi", False, 0, error=f"reseau:{type(exc).__name__}", attempt=attempt)
                time.sleep(2)
                continue
            if status in (301, 302, 303):
                ctx.record(kind, "envoi", True, wait_seconds, attempt=attempt, upload=upload_seconds, size=len(data))
                return
            category = f"http_{status}"
            if status == 200:
                category = next((key for key, text in ERROR_PATTERNS if text in body), "")
                if not category:
                    found = re.search(r'errorlist[^>]*>\s*<li>(.*?)</li>', body, re.S)
                    category = "refus:" + (re.sub(r"\s+", " ", found.group(1))[:60] if found else "formulaire_200")
            ctx.record(kind, "envoi", False, wait_seconds, error=category, attempt=attempt, upload=upload_seconds, size=len(data))
            if category in ("session_limit", "event_quota", "format"):
                return
            time.sleep(ctx.retry_delay if category in ("cooldown", "ip_limit") else 3)
        # abandon apres plusieurs tentatives
        ctx.abandoned += 1


class ScenarioRun:
    def __init__(self, command, name, options, event, distinct_ips, guests, per_guest, ramp, think, video_share, media):
        self.cmd, self.name, self.event = command, name, event
        self.parsed = urllib.parse.urlparse(options["base_url"])
        self.entry_path = event.get_public_url()
        self.form_path = f"{event.get_public_url()}souvenir/"
        self.distinct_ips, self.guests, self.per_guest = distinct_ips, guests, per_guest
        self.ramp_seconds, self.think, self.video_share = ramp, think, video_share
        self.photos, self.videos = media
        self.seed = options["seed"]
        self.max_attempts, self.retry_delay = options["max_attempts"], options["retry_delay"]
        self.lock = threading.Lock()
        self.records = []
        self.abandoned = 0
        self.probe_times = []
        self.stop_probe = threading.Event()

    def record(self, kind, step, ok, seconds, error="", attempt=1, upload=0.0, size=0):
        with self.lock:
            self.records.append(dict(kind=kind, step=step, ok=ok, seconds=seconds, error=error, attempt=attempt, upload=upload, size=size, at=time.time()))

    def probe(self):
        """Un nouvel invite qui scanne le QR pendant la charge : temps de reponse de la page."""
        while not self.stop_probe.is_set():
            cls = http.client.HTTPSConnection if self.parsed.scheme == "https" else http.client.HTTPConnection
            started = time.time()
            try:
                conn = cls(self.parsed.hostname, self.parsed.port, timeout=120)
                conn.request("GET", self.form_path, headers={"Host": self.parsed.netloc, "User-Agent": "MemoraProbe/1.0"})
                response = conn.getresponse()
                response.read()
                conn.close()
                ok = response.status == 200
            except Exception:  # noqa: BLE001
                ok = False
            with self.lock:
                self.probe_times.append((time.time() - started, ok))
            self.stop_probe.wait(2.0)


class Command(BaseCommand):
    help = "Test de charge du parcours invite (voir l'en-tete du module)."

    def add_arguments(self, parser):
        parser.add_argument("--base-url", required=True, help="Adresse du site a tester, ex. https://memoracd.site")
        parser.add_argument("--scenarios", default="A,B,C")
        parser.add_argument("--guests", type=int, default=100)
        parser.add_argument("--per-guest", type=int, default=5)
        parser.add_argument("--ramp", type=int, default=90, help="Secondes sur lesquelles les invites arrivent (scenarios A et B).")
        parser.add_argument("--think-min", type=float, default=10.0)
        parser.add_argument("--think-max", type=float, default=25.0)
        parser.add_argument("--video-share", type=float, default=0.2)
        parser.add_argument("--max-attempts", type=int, default=4)
        parser.add_argument("--retry-delay", type=float, default=4.0)
        parser.add_argument("--seed", type=int, default=11)

    def say(self, text=""):
        self.stdout.write(text)
        self.stdout.flush()

    def _media(self):
        rng = random.Random(3)
        ffmpeg = settings.MEMORA_FFMPEG_BINARY
        encoders = _encoders(ffmpeg)
        photos = [("photo", f"memora-photo-{i}.jpg", "image/jpeg", _make_photo(rng, landscape=False)) for i in range(4)]
        videos = []
        for i in range(3):
            container = "webm" if i == 2 else "mp4"
            data, err = _make_video(ffmpeg, encoders, i, landscape=False, container=container)
            if data:
                videos.append(("video", f"memora-video-{i}.{container}", "video/webm" if container == "webm" else "video/mp4", data))
        if not videos:
            raise CommandError("Impossible de generer les videos de test (ffmpeg).")
        self.say(f"Medias : photos {statistics.mean(len(p[3]) for p in photos) / 1e3:.0f} Ko en moyenne, videos {statistics.mean(len(v[3]) for v in videos) / 1e6:.1f} Mo en moyenne")
        return photos, videos

    def _event(self, label):
        user, _ = get_user_model().objects.get_or_create(username=BOT_USERNAME)
        user.set_unusable_password()
        user.save()
        event = Event.objects.create(
            organizer=user, title=f"Test de charge {label} {timezone.localtime():%H%M%S}", couple_name="Charge",
            event_type=EventType.objects.get(code="wedding"), event_date=timezone.localdate(),
        )
        event.mark_paid(provider="loadtest")
        event.guest_preview_enabled = True
        event.save()
        return event

    def handle(self, *args, **options):
        if not options["base_url"].startswith("http"):
            raise CommandError("--base-url doit commencer par http(s)://")
        self.options = options
        media = self._media()
        self.say(
            f"Site : {options['base_url']} - regles en vigueur : {settings.MEMORA_SESSION_UPLOAD_LIMIT} envois/invite, "
            f"{settings.MEMORA_IP_UPLOAD_LIMIT} envois/adresse IP, pause {settings.MEMORA_UPLOAD_COOLDOWN_SECONDS} s (invite ET adresse), "
            f"quota evenement sans formule {settings.MEMORA_EVENT_UPLOAD_LIMIT}"
        )
        plans = ", ".join(f"{p.label}={p.upload_quota}" for p in EventPlan.objects.filter(is_active=True))
        self.say(f"Quotas de souvenirs par formule : {plans}")
        for name in [s.strip().upper() for s in options["scenarios"].split(",") if s.strip()]:
            self._scenario(name, media)

    def _scenario(self, name, media):
        o = self.options
        if name == "A":
            label, distinct, guests, per_guest, ramp, think, video_share = "A distinctes", True, o["guests"], o["per_guest"], o["ramp"], (o["think_min"], o["think_max"]), o["video_share"]
        elif name == "B":
            label, distinct, guests, per_guest, ramp, think, video_share = "B meme IP", False, o["guests"], o["per_guest"], o["ramp"], (o["think_min"], o["think_max"]), o["video_share"]
        elif name == "C":
            label, distinct, guests, per_guest, ramp, think, video_share = "C pic", True, o["guests"], 1, 8, (0, 0), 1.0
        else:
            raise CommandError(f"Scenario inconnu : {name}")
        event = self._event(name)
        run = ScenarioRun(self, name, o, event, distinct, guests, per_guest, ramp, think, video_share, media)
        self.say(f"\n=== Scenario {label} : {guests} invites x {per_guest} envoi(s), arrivee sur {ramp} s, "
                 f"{'adresses IP differentes' if distinct else 'UNE SEULE adresse IP'}, {int(video_share * 100)} % de videos")
        try:
            started = time.time()
            probe = threading.Thread(target=run.probe, daemon=True)
            probe.start()
            crowd = [Guest(i, run) for i in range(guests)]
            for guest in crowd:
                guest.start()
            for guest in crowd:
                guest.join()
            run.stop_probe.set()
            probe.join(timeout=10)
            self._report(run, time.time() - started)
        finally:
            try:
                delete_event(event)
                self.say("  (evenement de test supprime)")
            except Exception as exc:  # noqa: BLE001
                self.say(f"  ! nettoyage incomplet : {type(exc).__name__}: {exc}")

    def _report(self, run, duration):
        sends = [r for r in run.records if r["step"] == "envoi"]
        first = [r for r in sends if r["attempt"] == 1]
        ok = [r for r in sends if r["ok"]]
        guests_total = run.guests * run.per_guest
        errors = {}
        for record in sends:
            if not record["ok"]:
                errors[record["error"]] = errors.get(record["error"], 0) + 1
        stored = run.event.guest_uploads.count()
        self.say(f"  duree totale {duration:.0f} s - souvenirs voulus {guests_total} - ENREGISTRES cote serveur : {stored} ({100 * stored / guests_total:.0f} %)")
        self.say(f"  tentatives d'envoi : {len(sends)} dont {len(first)} premieres ; reussies {len(ok)} ; reussies du 1er coup {sum(1 for r in first if r['ok'])} ; abandons apres {run.max_attempts} essais : {run.abandoned}")
        if errors:
            self.say("  refus / erreurs : " + ", ".join(f"{k}={v}" for k, v in sorted(errors.items(), key=lambda kv: -kv[1])))
        waits = [r["seconds"] for r in ok]
        if waits:
            self.say(f"  attente du serveur apres l'envoi (validation + stockage) : mediane {_percentile(waits, 50):.2f} s, p90 {_percentile(waits, 90):.2f} s, p99 {_percentile(waits, 99):.2f} s, max {max(waits):.2f} s")
        for kind in ("photo", "video"):
            subset = [r["seconds"] for r in ok if r["kind"] == kind]
            if subset:
                self.say(f"    {kind} : {len(subset)} reussis, attente serveur mediane {statistics.median(subset):.2f} s, p90 {_percentile(subset, 90):.2f} s")
        pages = [r["seconds"] for r in run.records if r["kind"] == "page"]
        page_fail = sum(1 for r in run.records if r["kind"] == "page" and not r["ok"])
        if pages:
            self.say(f"  pages d'entree/formulaire des invites : {len(pages)} chargements, mediane {statistics.median(pages):.2f} s, p90 {_percentile(pages, 90):.2f} s, echecs {page_fail}")
        probes = [t for t, _ in run.probe_times]
        probe_fail = sum(1 for _, good in run.probe_times if not good)
        if probes:
            self.say(f"  SONDE (un nouvel invite scanne le QR pendant la charge) : {len(probes)} mesures, mediane {statistics.median(probes):.2f} s, p90 {_percentile(probes, 90):.2f} s, pire {max(probes):.2f} s, echecs {probe_fail}")
        if duration:
            self.say(f"  debit serveur : {len(ok) / duration * 60:.0f} souvenirs/min en moyenne, {sum(r['size'] for r in ok) / duration / 1e6:.2f} Mo/s")
