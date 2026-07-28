"""Unicite e-mail / nom d'utilisateur, et recuperation de mot de passe."""
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from core.models import SiteConfiguration

SIGNUP_BASE = {
    "password1": "a-strong-test-password-42",
    "password2": "a-strong-test-password-42",
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
