"""Notifications WhatsApp au proprietaire : nouvel evenement et alertes critiques."""
from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from core import notifications, operations
from core.models import SiteConfiguration
from events.models import Event, EventPlan, EventType


class ImmediateThread:
    """Thread de test : execute la cible tout de suite (pas d'attente d'un fil d'arriere-plan)."""

    def __init__(self, target=None, args=(), daemon=None):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)


CONFIGURED = dict(MEMORA_NOTIFY_WHATSAPP_APIKEY="cle-secrete", MEMORA_NOTIFY_WHATSAPP_PHONE="+243 842 616 570", MEMORA_PUBLIC_BASE_URL="https://memoracd.site")


def create_event(username="orga-notif", title="Mariage Lea et Sam"):
    organizer = get_user_model().objects.create_user(username=username, password="x", email=f"{username}@example.org")
    return Event.objects.create(
        organizer=organizer, title=title, event_type=EventType.objects.get(code="wedding"), event_date=date(2026, 9, 26),
        plan=EventPlan.objects.get(code="grand-jour"),
    )


@patch("core.notifications.threading.Thread", ImmediateThread)
class EventCreatedNotificationTests(TestCase):
    @override_settings(**CONFIGURED)
    def test_a_new_event_sends_one_whatsapp_message_without_personal_data(self):
        with patch("core.notifications._send") as send, self.captureOnCommitCallbacks(execute=True):
            event = create_event()

        send.assert_called_once()
        phone, apikey, text = send.call_args.args
        self.assertEqual((phone, apikey), ("243842616570", "cle-secrete"))
        self.assertIn("« Mariage Lea et Sam » le 26/09/2026", text)
        self.assertIn("Organisateur : orga-notif", text)
        self.assertIn("Grand jour", text)
        self.assertIn(f"https://memoracd.site/admin/events/event/{event.pk}/change/", text)
        self.assertNotIn("@", text)  # ni e-mail ni coordonnees de l'organisateur

    def test_without_an_api_key_nothing_is_sent_and_nothing_breaks(self):
        with patch("core.notifications._send") as send, self.captureOnCommitCallbacks(execute=True):
            create_event()

        send.assert_not_called()

    @override_settings(**CONFIGURED)
    def test_test_and_tooling_accounts_never_notify(self):
        with patch("core.notifications._send") as send, self.captureOnCommitCallbacks(execute=True):
            for name in ("loadtest-bot", "rehearsal-bot-a1b2c3", "e2eorg-orga", "shot-amb"):
                create_event(username=name, title=f"Evt {name}")

        send.assert_not_called()

    @override_settings(**CONFIGURED)
    def test_a_provider_failure_never_breaks_event_creation(self):
        with patch("core.notifications._send", side_effect=OSError("reseau")), self.captureOnCommitCallbacks(execute=True):
            event = create_event()

        self.assertTrue(Event.objects.filter(pk=event.pk).exists())

    @override_settings(**{**CONFIGURED, "MEMORA_NOTIFY_WHATSAPP_PHONE": ""})
    def test_the_phone_defaults_to_the_whatsapp_number_of_the_configuration(self):
        configuration = SiteConfiguration.current()
        configuration.support_whatsapp = "+243 842 616 570"
        configuration.save()

        with patch("core.notifications._send") as send, self.captureOnCommitCallbacks(execute=True):
            create_event()

        self.assertEqual(send.call_args.args[0], "243842616570")

    @override_settings(**CONFIGURED)
    def test_the_message_is_a_callmebot_request_with_the_right_parameters(self):
        with patch("core.notifications.urllib.request.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.status = 200
            notifications.notify_owner("Bonjour", background=False)

        url = urlopen.call_args.args[0]
        self.assertTrue(url.startswith("https://api.callmebot.com/whatsapp.php?"))
        self.assertIn("phone=%2B243842616570", url)
        self.assertIn("apikey=cle-secrete", url)
        self.assertIn("text=Bonjour", url)
        self.assertEqual(urlopen.call_args.kwargs["timeout"], notifications.TIMEOUT_SECONDS)


@patch("core.notifications.threading.Thread", ImmediateThread)
@override_settings(**CONFIGURED, EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", MEMORA_ALERT_EMAILS=["a@example.org"])
class AlertNotificationTests(TestCase):
    def test_a_critical_alert_is_also_sent_on_whatsapp(self):
        issue = operations.Issue("film-x", "Film en échec — Mariage", "Le film a échoué.\nDétail")

        with patch("core.notifications._send") as send:
            operations.send_alert(issue, timezone.now())

        send.assert_called_once()
        self.assertIn("Film en échec — Mariage", send.call_args.args[2])
        self.assertIn("Le film a échoué.", send.call_args.args[2])
