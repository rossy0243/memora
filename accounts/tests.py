from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class OrganizerSignupTests(TestCase):
    def test_signup_creates_and_logs_in_organizer(self):
        response = self.client.post(
            reverse("accounts:signup"),
            {
                "username": "organizer",
                "email": "organizer@example.com",
                "password1": "a-strong-test-password-42",
                "password2": "a-strong-test-password-42",
            },
        )

        self.assertRedirects(response, reverse("dashboard:home"))
        self.assertTrue(get_user_model().objects.filter(username="organizer").exists())
        self.assertIn("_auth_user_id", self.client.session)
