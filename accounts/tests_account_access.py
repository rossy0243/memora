"""Unicite e-mail / nom d'utilisateur, et recuperation de mot de passe."""
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from accounts.models import OrganizerProfile
from core.models import SiteConfiguration

SIGNUP_BASE = {
    "password1": "a-strong-test-password-42",
    "password2": "a-strong-test-password-42",
    "accept_terms": "on",
}


class EmailUniquenessTests(TestCase):
    def setUp(self):
        cache.clear()
        get_user_model().objects.create_user(
            username="premier", email="Camille@Memora.test", password="secret"
        )

    def _signup(self, username, email):
        return self.client.post(
            reverse("accounts:signup"), {**SIGNUP_BASE, "username": username, "email": email}
        )

    def test_same_email_is_refused(self):
        response = self._signup("second", "Camille@Memora.test")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Un compte existe déjà avec cette adresse e-mail.")
        self.assertFalse(get_user_model().objects.filter(username="second").exists())

    def test_same_email_in_a_different_case_is_refused(self):
        """« camille@... » et « Camille@... » sont la meme boite aux lettres."""
        response = self._signup("second", "CAMILLE@memora.TEST")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Un compte existe déjà avec cette adresse e-mail.")

    def test_a_new_email_is_accepted_and_stored_lowercase(self):
        response = self._signup("nouveau", "Noe@Memora.test")

        self.assertRedirects(response, reverse("dashboard:home"))
        user = get_user_model().objects.get(username="nouveau")
        self.assertEqual(user.email, "noe@memora.test")

    def test_database_refuses_a_duplicate_even_without_the_form(self):
        """Garde-fou contre deux inscriptions simultanees : l'index le refuse."""
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                get_user_model().objects.create_user(
                    username="contournement", email="camille@memora.test", password="secret"
                )

    def test_accounts_without_email_are_not_blocked(self):
        """L'index est partiel : plusieurs comptes techniques sans e-mail restent possibles."""
        get_user_model().objects.create_user(username="technique1", password="secret")
        get_user_model().objects.create_user(username="technique2", password="secret")
        self.assertEqual(get_user_model().objects.filter(email="").count(), 2)


class UsernameUniquenessTests(TestCase):
    def setUp(self):
        cache.clear()
        get_user_model().objects.create_user(
            username="Marie", email="marie@memora.test", password="secret"
        )

    def test_same_username_is_refused(self):
        response = self.client.post(
            reverse("accounts:signup"),
            {**SIGNUP_BASE, "username": "Marie", "email": "autre@memora.test"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(get_user_model().objects.filter(username__iexact="marie").count(), 1)

    def test_same_username_in_a_different_case_is_refused(self):
        """Sinon « marie » et « Marie » cohabiteraient et pretaient a confusion."""
        response = self.client.post(
            reverse("accounts:signup"),
            {**SIGNUP_BASE, "username": "marie", "email": "autre@memora.test"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ce nom d&#x27;utilisateur est déjà pris.")
        self.assertEqual(get_user_model().objects.filter(username__iexact="marie").count(), 1)


class PasswordHelpTests(TestCase):
    def setUp(self):
        cache.clear()

    def _configure(self, **fields):
        config = SiteConfiguration.current()
        for key, value in fields.items():
            setattr(config, key, value)
        config.save()
        return config

    def test_login_page_links_to_password_help(self):
        response = self.client.get(reverse("accounts:login"))
        self.assertContains(response, reverse("accounts:password_help"))
        self.assertContains(response, "Mot de passe oublié")

    def test_page_shows_whatsapp_and_email_from_admin(self):
        self._configure(
            support_email="aide@memora.test", support_whatsapp="+243 990 000 111"
        )

        response = self.client.get(reverse("accounts:password_help"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "https://wa.me/243990000111")  # sans + ni espaces
        self.assertContains(response, "mailto:aide@memora.test")
        self.assertContains(response, "+243 990 000 111")

    def test_whatsapp_alone_is_enough(self):
        self._configure(support_email="", support_whatsapp="+243990000111", legal_contact_email="")

        response = self.client.get(reverse("accounts:password_help"))

        self.assertContains(response, "wa.me/243990000111")
        self.assertNotContains(response, "mailto:")

    def test_falls_back_to_the_legal_contact_email(self):
        self._configure(
            support_email="", support_whatsapp="", legal_contact_email="legal@memora.test"
        )

        response = self.client.get(reverse("accounts:password_help"))

        self.assertContains(response, "mailto:legal@memora.test")

    def test_page_stays_usable_without_any_contact_configured(self):
        self._configure(support_email="", support_whatsapp="", legal_contact_email="")

        response = self.client.get(reverse("accounts:password_help"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "pas encore disponible")

    def test_page_is_not_indexed(self):
        response = self.client.get(reverse("accounts:password_help"))
        self.assertContains(response, "noindex")

    def test_page_links_to_the_email_reset_flow(self):
        response = self.client.get(reverse("accounts:password_help"))
        self.assertContains(response, reverse("accounts:password_reset"))


class SignupTermsAcceptanceTests(TestCase):
    """La case CGU est obligatoire, et sa date d'acceptation est tracee."""

    def setUp(self):
        cache.clear()

    def test_signup_without_accepting_terms_is_rejected(self):
        response = self.client.post(
            reverse("accounts:signup"),
            {**SIGNUP_BASE, "username": "sans-cgu", "email": "sanscgu@memora.test", "accept_terms": ""},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Vous devez accepter les CGU")
        self.assertFalse(get_user_model().objects.filter(username="sans-cgu").exists())

    def test_signup_records_terms_acceptance_timestamp(self):
        response = self.client.post(
            reverse("accounts:signup"),
            {**SIGNUP_BASE, "username": "avec-cgu", "email": "aveccgu@memora.test"},
        )

        self.assertRedirects(response, reverse("dashboard:home"))
        user = get_user_model().objects.get(username="avec-cgu")
        self.assertIsNotNone(OrganizerProfile.for_user(user).terms_accepted_at)

    def test_signup_page_links_to_cgu_and_privacy(self):
        response = self.client.get(reverse("accounts:signup"))

        self.assertContains(response, reverse("core:terms"))
        self.assertContains(response, reverse("core:privacy"))


class PasswordResetFlowTests(TestCase):
    """Lien de reinitialisation par e-mail, en plus du contact humain existant."""

    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="oublieux", email="oublieux@memora.test", password="ancien-mot-de-passe-42"
        )

    def test_requesting_a_reset_sends_an_email_with_a_working_link(self):
        from django.core import mail

        response = self.client.post(
            reverse("accounts:password_reset"), {"email": "oublieux@memora.test"}
        )

        self.assertRedirects(response, reverse("accounts:password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("oublieux@memora.test", mail.outbox[0].to)
        self.assertIn(reverse("accounts:password_reset"), mail.outbox[0].body)

    def test_unknown_email_does_not_error_or_reveal_account_existence(self):
        from django.core import mail

        response = self.client.post(
            reverse("accounts:password_reset"), {"email": "inconnu@memora.test"}
        )

        self.assertRedirects(response, reverse("accounts:password_reset_done"))
        self.assertEqual(len(mail.outbox), 0)

    def test_valid_link_allows_setting_a_new_password(self):
        uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        token = default_token_generator.make_token(self.user)

        confirm_url = reverse("accounts:password_reset_confirm", kwargs={"uidb64": uid, "token": token})
        session = self.client.session
        response = self.client.get(confirm_url, follow=True)
        # Django echange le token de l'URL contre un token de session au premier
        # GET, pour eviter qu'il ne se retrouve dans les logs/referrers ensuite.
        set_password_url = response.redirect_chain[-1][0]

        response = self.client.post(
            set_password_url,
            {"new_password1": "un-nouveau-mot-de-passe-42", "new_password2": "un-nouveau-mot-de-passe-42"},
        )

        self.assertRedirects(response, reverse("accounts:password_reset_complete"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("un-nouveau-mot-de-passe-42"))

    def test_invalid_token_shows_an_error_with_a_way_forward(self):
        uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        confirm_url = reverse(
            "accounts:password_reset_confirm", kwargs={"uidb64": uid, "token": "bogus-token"}
        )

        response = self.client.get(confirm_url)

        self.assertContains(response, "invalide")
        self.assertContains(response, reverse("accounts:password_help"))


class PasswordChangeTests(TestCase):
    """Changement de mot de passe depuis le compte (organisateur et agent)."""

    OLD = "ancien-mot-de-passe-42"
    NEW = "un-nouveau-mot-de-passe-42"

    def setUp(self):
        cache.clear()
        self.organizer = get_user_model().objects.create_user(
            username="orga", email="orga@memora.test", password=self.OLD
        )
        self.agent = get_user_model().objects.create_user(
            username="agent", email="agent@memora.test", password=self.OLD
        )
        from accounts.models import AgentProfile

        AgentProfile.objects.create(user=self.agent)

    def _change(self, old=None, new=None, confirm=None):
        return self.client.post(
            reverse("accounts:password_change"),
            {
                "old_password": old or self.OLD,
                "new_password1": new or self.NEW,
                "new_password2": confirm or new or self.NEW,
            },
        )

    def test_anonymous_user_is_sent_to_login(self):
        response = self.client.get(reverse("accounts:password_change"))

        self.assertRedirects(
            response, f"{reverse('accounts:login')}?next={reverse('accounts:password_change')}"
        )

    def test_organizer_can_change_password_and_stays_logged_in(self):
        self.client.login(username="orga", password=self.OLD)

        response = self._change()

        self.assertRedirects(response, reverse("dashboard:home"))
        self.organizer.refresh_from_db()
        self.assertTrue(self.organizer.check_password(self.NEW))
        self.assertEqual(self.client.get(reverse("dashboard:home")).status_code, 200)

    def test_agent_can_change_password_and_lands_on_missions(self):
        self.client.login(username="agent", password=self.OLD)

        response = self._change()

        self.assertRedirects(response, reverse("guestbook:agent_home"))
        self.agent.refresh_from_db()
        self.assertTrue(self.agent.check_password(self.NEW))

    def test_wrong_current_password_is_refused(self):
        self.client.login(username="orga", password=self.OLD)

        response = self._change(old="pas-le-bon-mot-de-passe")

        self.assertEqual(response.status_code, 200)
        self.organizer.refresh_from_db()
        self.assertTrue(self.organizer.check_password(self.OLD))

    def test_weak_or_mismatched_new_password_is_refused(self):
        self.client.login(username="orga", password=self.OLD)

        self.assertEqual(self._change(new="12345678").status_code, 200)
        self.assertEqual(self._change(new=self.NEW, confirm="autre-chose-42-xyz").status_code, 200)
        self.organizer.refresh_from_db()
        self.assertTrue(self.organizer.check_password(self.OLD))

    def test_account_menu_offers_the_link_to_both_roles(self):
        link = reverse("accounts:password_change")
        self.client.login(username="orga", password=self.OLD)
        self.assertContains(self.client.get(reverse("dashboard:home")), link)

        self.client.login(username="agent", password=self.OLD)
        self.assertContains(self.client.get(reverse("guestbook:agent_home")), link)
