"""Conservation : date de retrait des souvenirs, garde-fou « pas avant le film », rappels a l'organisateur."""
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from events import reminders
from events.models import Event, EventType
from events.services import media_removal_date
from processing.models import GeneratedMovie
from uploads.models import GuestUpload


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", MEMORA_PUBLIC_BASE_URL="https://memoracd.site")
class RetentionTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.organizer = get_user_model().objects.create_user(username="orga-ret", password="x", email="orga-ret@example.org")

    def event(self, days_ago, paid=True, title=None, email=True):
        event = Event.objects.create(
            organizer=self.organizer, title=title or f"Evt {days_ago}", event_type=EventType.objects.get(code="wedding"),
            event_date=self.today - timedelta(days=days_ago),
        )
        if paid:
            event.mark_paid(provider="test")
            event.save()
        GuestUpload.objects.create(
            event=event, category=event.upload_categories.first(), media_file="x.jpg", media_type="image",
            original_filename="x.jpg", file_size=1,
        )
        return event

    def film(self, event):
        return GeneratedMovie.objects.create(event=event, status=GeneratedMovie.Status.COMPLETED, final_file="films/x.mp4")

    # -- date de retrait et garde-fou ----------------------------------------------------------------
    def test_removal_waits_for_the_film_of_a_paid_event(self):
        event = self.event(0)
        self.assertEqual(media_removal_date(event), event.event_date + timedelta(days=7 + 14))

        self.film(event)
        self.assertEqual(media_removal_date(event), event.event_date + timedelta(days=7))

        unpaid = self.event(0, paid=False, title="Non paye")
        self.assertEqual(media_removal_date(unpaid), unpaid.event_date + timedelta(days=7))

    def test_a_paid_event_without_film_keeps_its_souvenirs_past_day_seven(self):
        """Un film en echec doit pouvoir etre relance apres le J+7 : ses souvenirs restent 14 jours de plus."""
        event = self.event(8)
        call_command("cleanup_expired_media", stdout=StringIO())
        self.assertFalse(GuestUpload.objects.get(event=event).is_deleted)

        Event.objects.filter(pk=event.pk).update(event_date=self.today - timedelta(days=22))
        call_command("cleanup_expired_media", stdout=StringIO())
        self.assertTrue(GuestUpload.objects.get(event=event).is_deleted)

    def test_a_paid_event_with_its_film_is_masked_on_day_seven(self):
        event = self.event(8)
        self.film(event)

        call_command("cleanup_expired_media", stdout=StringIO())

        self.assertTrue(GuestUpload.objects.get(event=event).is_deleted)

    # -- rappel avant retrait des souvenirs -----------------------------------------------------------
    def test_reminder_goes_out_two_days_before_removal_and_only_once(self):
        event = self.event(5)  # retrait a J+7 (film present) -> dans 2 jours
        self.film(event)

        self.assertEqual([e.pk for e, _ in reminders.originals_reminders_due()], [event.pk])
        call_command("send_retention_reminders", stdout=StringIO())
        call_command("send_retention_reminders", stdout=StringIO())

        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ["orga-ret@example.org"])
        removal = event.event_date + timedelta(days=7)
        self.assertIn(f"{removal:%d/%m/%Y}", message.subject)
        self.assertIn(f"https://memoracd.site/evenements/{event.pk}/", message.body)
        self.assertIn("film souvenir", message.body)
        event.refresh_from_db()
        self.assertIsNotNone(event.retention_reminder_sent_at)

    def test_no_reminder_too_early_too_late_or_without_anything_to_lose(self):
        early = self.event(2, title="Trop tot")
        self.film(early)
        late = self.event(9, title="Trop tard")
        self.film(late)
        empty = self.event(5, title="Vide")
        self.film(empty)
        GuestUpload.objects.filter(event=empty).update(is_deleted=True)
        unpaid = self.event(5, paid=False, title="Non paye")
        no_mail = self.event(5, title="Sans e-mail")
        self.film(no_mail)
        get_user_model().objects.filter(pk=self.organizer.pk).update(email="")

        self.assertEqual(list(reminders.originals_reminders_due()), [])
        call_command("send_retention_reminders", stdout=StringIO())
        self.assertEqual(len(mail.outbox), 0)
        self.assertIsNotNone(unpaid)

    def test_reminder_follows_the_extended_removal_date_when_the_film_is_missing(self):
        """Sans film, le retrait est repousse de 14 jours : le rappel aussi (pas d'e-mail trompeur a J+5)."""
        event = self.event(5)

        self.assertEqual(list(reminders.originals_reminders_due()), [])
        Event.objects.filter(pk=event.pk).update(event_date=self.today - timedelta(days=19))  # retrait dans 2 jours
        self.assertEqual([e.pk for e, _ in reminders.originals_reminders_due()], [event.pk])

    def test_a_failed_email_is_retried_the_next_day(self):
        event = self.event(5)
        self.film(event)
        with patch("events.reminders.send_mail", side_effect=OSError("smtp")):
            call_command("send_retention_reminders", stdout=StringIO())
        event.refresh_from_db()
        self.assertIsNone(event.retention_reminder_sent_at)

        call_command("send_retention_reminders", stdout=StringIO())
        self.assertEqual(len(mail.outbox), 1)

    # -- rappel avant suppression du film --------------------------------------------------------------
    def test_film_reminder_two_weeks_before_final_deletion(self):
        event = self.event(83)  # suppression a J+97 -> dans 14 jours
        self.film(event)

        self.assertEqual([e.pk for e, _ in reminders.film_reminders_due()], [event.pk])
        call_command("send_retention_reminders", stdout=StringIO())
        call_command("send_retention_reminders", stdout=StringIO())

        film_mails = [m for m in mail.outbox if "film" in m.subject.lower() and "supprimé" in m.subject]
        self.assertEqual(len(film_mails), 1)
        self.assertIn(f"{reminders.deliverable_deletion_date(event):%d/%m/%Y}", film_mails[0].subject)

    def test_dry_run_lists_without_sending(self):
        event = self.event(5)
        self.film(event)
        out = StringIO()

        call_command("send_retention_reminders", "--dry-run", stdout=out)

        self.assertIn("[dry-run]", out.getvalue())
        self.assertEqual(len(mail.outbox), 0)
        event.refresh_from_db()
        self.assertIsNone(event.retention_reminder_sent_at)
