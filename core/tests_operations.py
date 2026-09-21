"""Exploitation : alertes, battements de coeur, page de sante approfondie, sauvegarde, entretien quotidien."""
import gzip
import json
import shutil
import tempfile
from datetime import datetime, timedelta, timezone as dt_timezone
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.files.storage import default_storage
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core import operations
from core.models import OperationalState, SiteConfiguration
from events.models import Event, EventType
from guestbook.models import GuestBookMovie
from processing.models import GeneratedMovie

TEST_MEDIA_ROOT = tempfile.mkdtemp()


def make_event(title="Mariage Alerte", event_date=None, paid=True):
    organizer = get_user_model().objects.get_or_create(username="orga-ops", defaults={"email": "orga-ops@example.org"})[0]
    event = Event.objects.create(
        organizer=organizer, title=title, event_type=EventType.objects.get(code="wedding"),
        event_date=event_date or timezone.localdate() - timedelta(days=1),
    )
    if paid:
        event.mark_paid(provider="test")
        event.save()
    return event


def age(movie, **delta):
    """Vieillit un enregistrement (updated_at est auto : on passe par update)."""
    type(movie).objects.filter(pk=movie.pk).update(updated_at=timezone.now() - timedelta(**delta))


@override_settings(MEMORA_ALERT_EMAILS=["alertes@example.org"], EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class AlertDetectionTests(TestCase):
    def test_a_failed_film_raises_an_issue_until_a_film_succeeds(self):
        event = make_event()
        failed = GeneratedMovie.objects.create(event=event, status=GeneratedMovie.Status.FAILED, error_logs="boom", progress_message="interrompue")

        issues = operations.collect_issues()
        self.assertEqual([i.key for i in issues], [f"movie-failed:{failed.pk}"])
        self.assertIn("boom", issues[0].detail)

        GeneratedMovie.objects.create(event=event, status=GeneratedMovie.Status.COMPLETED)
        self.assertEqual(operations.collect_issues(), [])

    def test_stuck_films_are_reported_but_a_moving_render_is_not(self):
        event = make_event()
        pending = GeneratedMovie.objects.create(event=event, status=GeneratedMovie.Status.PENDING)
        age(pending, minutes=50)
        self.assertEqual([i.key for i in operations.collect_issues()], [f"movie-stuck:{pending.pk}"])

        age(pending, minutes=10)
        self.assertEqual(operations.collect_issues(), [])  # vient d'etre mis a jour

        pending.status = GeneratedMovie.Status.PROCESSING
        pending.save(update_fields=["status"])
        age(pending, minutes=60)  # rendu long qui bouge encore (progression toutes les minutes)
        self.assertEqual(operations.collect_issues(), [])
        age(pending, minutes=90)
        self.assertEqual([i.key for i in operations.collect_issues()], [f"movie-stuck:{pending.pk}"])

    def test_an_overdue_event_without_any_film_is_reported(self):
        from uploads.models import GuestUpload

        event = make_event(event_date=timezone.localdate() - timedelta(days=3))
        GuestUpload.objects.create(
            event=event, category=event.upload_categories.first(), media_file="x.jpg", media_type="image",
            original_filename="x.jpg", file_size=1,
        )

        self.assertEqual([i.key for i in operations.collect_issues()], [f"movie-overdue:{event.pk}"])

    def test_a_failed_guestbook_montage_is_reported(self):
        event = make_event()
        montage = GuestBookMovie.objects.create(event=event, status=GuestBookMovie.Status.FAILED, error_message="ffmpeg")

        self.assertEqual([i.key for i in operations.collect_issues()], [f"guestbook-failed:{montage.pk}"])

    def test_silent_tasks_are_reported_after_a_first_silent_observation(self):
        # Premier passage : registre vide -> amorce, aucune alerte.
        self.assertEqual(operations.collect_issues(watch_film_cron=True, watch_maintenance=True), [])
        # Puis la tache des films se tait, la sauvegarde aussi.
        operations.beat(operations.FILM_CRON, timezone.now() - timedelta(hours=3))
        operations.beat(operations.BACKUP, timezone.now() - timedelta(hours=40))
        keys = {i.key for i in operations.collect_issues(watch_film_cron=True, watch_maintenance=True)}
        self.assertEqual(keys, {"film-cron-silent", f"{operations.BACKUP}-silent"})

    def test_the_film_cron_counts_as_alive_while_a_render_is_moving(self):
        event = make_event()
        operations.beat(operations.FILM_CRON, timezone.now() - timedelta(hours=3))
        GeneratedMovie.objects.create(event=event, status=GeneratedMovie.Status.PROCESSING)

        alive, _ = operations.film_cron_status()
        self.assertTrue(alive)


@override_settings(MEMORA_ALERT_EMAILS=["alertes@example.org"], EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class AlertSendingTests(TestCase):
    def setUp(self):
        self.issue = operations.Issue("k1", "Film en échec — X", "Détail du problème")

    def test_one_email_per_problem_then_a_reminder_after_twelve_hours(self):
        now = timezone.now()
        self.assertTrue(operations.send_alert(self.issue, now))
        self.assertFalse(operations.send_alert(self.issue, now + timedelta(hours=1)))
        self.assertTrue(operations.send_alert(self.issue, now + timedelta(hours=13)))
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(mail.outbox[0].to, ["alertes@example.org"])
        self.assertIn("[Memora] Alerte : Film en échec — X", mail.outbox[0].subject)

    def test_two_different_problems_are_two_emails(self):
        operations.send_alert(self.issue)
        operations.send_alert(operations.Issue("k2", "Autre", "Autre détail"))

        self.assertEqual(len(mail.outbox), 2)

    @override_settings(MEMORA_ALERT_EMAILS=[])
    def test_falls_back_to_the_support_address_and_never_sends_into_the_void(self):
        configuration = SiteConfiguration.current()
        configuration.support_email = "contact@example.org"
        configuration.save()
        self.assertEqual(operations.alert_recipients(), ["contact@example.org"])

        configuration.support_email = ""
        configuration.legal_contact_email = ""
        configuration.save()
        self.assertFalse(operations.send_alert(self.issue))
        self.assertEqual(len(mail.outbox), 0)

    def test_a_failing_email_is_retried_next_time_and_never_raises(self):
        with patch("core.operations.send_mail", side_effect=OSError("smtp down")):
            self.assertFalse(operations.send_alert(self.issue))
        self.assertFalse(OperationalState.objects.filter(key="alert:k1").exists())
        self.assertTrue(operations.send_alert(self.issue))

    def test_run_checks_never_raises(self):
        with patch("core.operations.collect_issues", side_effect=RuntimeError("bug")):
            self.assertEqual(operations.run_checks(), ([], 0))

    def test_check_command_reports_and_sends_a_test_email(self):
        out = StringIO()
        call_command("check_operations", "--test-email", stdout=out)

        self.assertIn("Alerte de test envoyee", out.getvalue())
        self.assertEqual(len(mail.outbox), 1)


class DeepHealthTests(TestCase):
    def test_plain_health_stays_ok_and_deep_health_follows_the_film_cron(self):
        url = reverse("core:health")
        self.assertEqual(self.client.get(url).content, b"ok")

        self.assertEqual(self.client.get(url, {"crons": "1"}).status_code, 503)  # jamais vue

        operations.beat(operations.FILM_CRON)
        self.assertEqual(self.client.get(url, {"crons": "1"}).content, b"ok")

        operations.beat(operations.FILM_CRON, timezone.now() - timedelta(hours=2))
        response = self.client.get(url, {"crons": "1"})
        self.assertEqual(response.status_code, 503)
        self.assertIn("silencieuse", response.content.decode())

    def test_deep_health_is_fine_during_a_long_render(self):
        operations.beat(operations.FILM_CRON, timezone.now() - timedelta(hours=2))
        GeneratedMovie.objects.create(event=make_event(), status=GeneratedMovie.Status.PROCESSING)

        self.assertEqual(self.client.get(reverse("core:health"), {"crons": "1"}).status_code, 200)


class FilmCronCommandTests(TestCase):
    def test_the_cron_beats_first_and_checks_last_without_ever_failing(self):
        with patch("processing.management.commands.run_movie_cron.call_command") as sub, \
                patch("processing.management.commands.run_movie_cron.operations.run_checks") as checks:
            call_command("run_movie_cron")

        self.assertIsNotNone(operations.last_beat(operations.FILM_CRON))
        self.assertEqual([c.args[0] for c in sub.call_args_list], ["generate_scheduled_movies", "process_pending_movies", "process_guestbook_movies"])
        checks.assert_called_once()


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT, MEMORA_BACKUP_KEEP=2)
class BackupTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def test_backup_is_written_readable_and_pruned(self):
        make_event("Mariage sauvegarde")
        for second in (1, 2, 3):
            with patch("core.management.commands.backup_database_to_storage.timezone") as fake:
                fake.now.return_value = datetime(2026, 1, 1, 0, 0, second, tzinfo=dt_timezone.utc)
                call_command("backup_database_to_storage", stdout=StringIO())

        files = sorted(default_storage.listdir("backups")[1])
        self.assertEqual(len(files), 2)  # les plus anciennes sont supprimees
        self.assertEqual(files[-1], "memora-db-20260101-000003.json.gz")
        with default_storage.open(f"backups/{files[-1]}", "rb") as handle:
            data = json.loads(gzip.decompress(handle.read()))
        self.assertTrue(any(item["model"] == "events.event" and item["fields"]["title"] == "Mariage sauvegarde" for item in data))
        self.assertFalse(any(item["model"] in ("sessions.session", "contenttypes.contenttype") for item in data))
        self.assertIsNotNone(operations.last_beat(operations.BACKUP))


class RestoreTests(TestCase):
    def test_a_backup_can_be_loaded_back_without_signal_duplicates(self):
        """Regression : recharger un compte ou un evenement declenchait les signaux « a la creation »
        (profil organisateur, categories par defaut) qui entraient en conflit avec le contenu du
        fichier -> restauration impossible. Les signaux ignorent maintenant les chargements bruts."""
        from accounts.models import OrganizerProfile
        from uploads.models import UploadCategory

        event = make_event("Restauration")
        user_id, event_id = event.organizer_id, event.pk
        before = (OrganizerProfile.objects.filter(user_id=user_id).count(), UploadCategory.objects.filter(event_id=event_id).count())
        self.assertGreater(before[1], 0)
        dump = StringIO()
        call_command("dumpdata", "auth.user", "accounts", "events.event", "uploads.uploadcategory", use_natural_foreign_keys=True, stdout=dump)
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as handle:
            handle.write(dump.getvalue())
        get_user_model().objects.filter(pk=user_id).delete()
        self.assertFalse(Event.objects.filter(pk=event_id).exists())

        call_command("loaddata", handle.name, verbosity=0)

        self.assertTrue(Event.objects.filter(pk=event_id, title="Restauration").exists())
        self.assertEqual(
            (OrganizerProfile.objects.filter(user_id=user_id).count(), UploadCategory.objects.filter(event_id=event_id).count()), before
        )


class DailyMaintenanceTests(TestCase):
    def test_one_failing_step_does_not_stop_the_others_but_fails_the_run(self):
        calls = []

        def fake(command, *args, **kwargs):
            calls.append(command)
            if command == "send_retention_reminders":
                raise RuntimeError("smtp")

        with patch("core.management.commands.run_daily_maintenance.call_command", side_effect=fake):
            with self.assertRaises(CommandError) as raised:
                call_command("run_daily_maintenance", stdout=StringIO())

        self.assertEqual(calls, ["cleanup_expired_media", "send_retention_reminders", "backup_database_to_storage"])
        self.assertIn("rappels de conservation", str(raised.exception))
        self.assertIsNotNone(operations.last_beat(operations.MAINTENANCE_CRON))


class LegalDatesCommandTests(TestCase):
    def test_dates_can_be_fixed_and_are_shown_on_the_legal_pages(self):
        from django.urls import reverse

        out = StringIO()
        call_command("set_legal_dates", "--cgu", "2026-09-21", "--privacy", "2026-09-22", stdout=out)

        self.assertIn("modifie", out.getvalue())
        self.assertContains(self.client.get(reverse("core:terms")), "En vigueur au 21/09/2026")
        self.assertContains(self.client.get(reverse("core:privacy")), "En vigueur au 22/09/2026")

    def test_an_invalid_date_is_refused(self):
        with self.assertRaises(CommandError):
            call_command("set_legal_dates", "--cgu", "21/09/2026", stdout=StringIO())
