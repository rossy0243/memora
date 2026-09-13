"""Candidature Ambassadeur : numero de piece d'identite + scan, analyse
heuristique de retouche, et decision (approbation/refus) en admin."""
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from PIL import Image

from .forms import AmbassadorApplicationForm
from .identity_check import analyze_identity_document
from .models import AmbassadorApplication, OrganizerProfile


def _make_image_file(name="id.jpg", size=(1000, 700), fmt="JPEG", exif=None):
    image = Image.new("RGB", size, color=(180, 180, 190))
    buffer = BytesIO()
    if exif is not None:
        buffer_kwargs = {"exif": exif.tobytes()}
    else:
        buffer_kwargs = {}
    image.save(buffer, format=fmt, **buffer_kwargs)
    buffer.seek(0)
    content_type = "image/jpeg" if fmt == "JPEG" else "image/png"
    return SimpleUploadedFile(name, buffer.read(), content_type=content_type)


class IdentityCheckHeuristicTests(TestCase):
    """L'analyse ne bloque jamais rien : elle ne fait que produire des indices."""

    def test_missing_exif_is_flagged(self):
        result = analyze_identity_document(_make_image_file())

        self.assertGreaterEqual(result["risk_score"], 15)
        self.assertTrue(any("EXIF" in flag for flag in result["flags"]))

    def test_editing_software_tag_is_flagged(self):
        exif = Image.Exif()
        exif[305] = "Adobe Photoshop 24.0"

        result = analyze_identity_document(_make_image_file(exif=exif))

        self.assertGreaterEqual(result["risk_score"], 40)
        self.assertTrue(any("Photoshop" in flag for flag in result["flags"]))

    def test_low_resolution_is_flagged(self):
        result = analyze_identity_document(_make_image_file(size=(300, 200)))

        self.assertTrue(any("Résolution faible" in flag for flag in result["flags"]))

    def test_score_is_capped_at_100(self):
        exif = Image.Exif()
        exif[305] = "GIMP 2.10"

        result = analyze_identity_document(_make_image_file(size=(300, 200), exif=exif))

        self.assertLessEqual(result["risk_score"], 100)

    def test_unreadable_file_does_not_raise(self):
        broken = SimpleUploadedFile("id.jpg", b"not an image", content_type="image/jpeg")

        result = analyze_identity_document(broken)

        self.assertEqual(result, {"risk_score": 0, "flags": []})


class AmbassadorApplicationFormTests(TestCase):
    def test_valid_jpeg_is_accepted_and_analyzed(self):
        form = AmbassadorApplicationForm(
            data={"id_document_number": "CD1234567"},
            files={"id_document_file": _make_image_file()},
        )

        self.assertTrue(form.is_valid(), form.errors)
        application = form.save(commit=False)
        self.assertGreaterEqual(application.tamper_risk_score, 0)
        self.assertIsInstance(application.tamper_flags, list)

    def test_non_image_file_is_rejected(self):
        fake = SimpleUploadedFile("id.jpg", b"not an image at all", content_type="image/jpeg")
        form = AmbassadorApplicationForm(
            data={"id_document_number": "CD1234567"},
            files={"id_document_file": fake},
        )

        self.assertFalse(form.is_valid())
        self.assertIn("id_document_file", form.errors)

    def test_oversized_file_is_rejected(self):
        upload = _make_image_file()
        upload.size = 11 * 1024 * 1024  # au-dela du plafond de 10 Mo
        form = AmbassadorApplicationForm(
            data={"id_document_number": "CD1234567"},
            files={"id_document_file": upload},
        )

        self.assertFalse(form.is_valid())
        self.assertIn("id_document_file", form.errors)

    def test_missing_document_number_is_rejected(self):
        form = AmbassadorApplicationForm(
            data={"id_document_number": ""},
            files={"id_document_file": _make_image_file()},
        )

        self.assertFalse(form.is_valid())
        self.assertIn("id_document_number", form.errors)


class BecomeAmbassadorViewTests(TestCase):
    def setUp(self):
        cache.clear()
        self.organizer = get_user_model().objects.create_user(
            username="candidat", password="secret"
        )

    def test_anonymous_is_redirected_to_login(self):
        response = self.client.get(reverse("accounts:become_ambassador"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)

    def test_ambassador_is_redirected_to_dashboard(self):
        profile = OrganizerProfile.for_user(self.organizer)
        profile.grant_ambassador()
        profile.save(update_fields=["is_ambassador", "became_ambassador_at", "updated_at"])
        self.client.force_login(self.organizer)

        response = self.client.get(reverse("accounts:become_ambassador"))

        self.assertRedirects(response, reverse("dashboard:home"))

    def test_simple_organizer_sees_the_form(self):
        self.client.force_login(self.organizer)

        response = self.client.get(reverse("accounts:become_ambassador"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Numéro de la pièce")

    def test_submitting_creates_a_pending_application(self):
        self.client.force_login(self.organizer)

        response = self.client.post(
            reverse("accounts:become_ambassador"),
            {"id_document_number": "CD1234567", "id_document_file": _make_image_file()},
        )

        self.assertRedirects(response, reverse("dashboard:home"))
        application = AmbassadorApplication.objects.get(organizer=self.organizer)
        self.assertEqual(application.status, AmbassadorApplication.Status.PENDING)

    def test_pending_application_blocks_a_second_submission(self):
        AmbassadorApplication.objects.create(
            organizer=self.organizer,
            id_document_number="CD1234567",
            id_document_file=_make_image_file(),
        )
        self.client.force_login(self.organizer)

        response = self.client.get(reverse("accounts:become_ambassador"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "en cours d'examen")
        self.assertNotContains(response, "Numéro de la pièce")

    def test_rejected_application_allows_resubmission(self):
        rejected = AmbassadorApplication.objects.create(
            organizer=self.organizer,
            id_document_number="CD1234567",
            id_document_file=_make_image_file(),
        )
        rejected.reject(note="Photo illisible")
        self.client.force_login(self.organizer)

        response = self.client.get(reverse("accounts:become_ambassador"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Photo illisible")
        self.assertContains(response, "Numéro de la pièce")


class AmbassadorApplicationDecisionTests(TestCase):
    def setUp(self):
        cache.clear()
        self.organizer = get_user_model().objects.create_user(
            username="candidat-decision", password="secret"
        )
        self.application = AmbassadorApplication.objects.create(
            organizer=self.organizer,
            id_document_number="CD1234567",
            id_document_file=_make_image_file(),
        )

    def test_approve_grants_ambassador_status(self):
        self.application.approve()

        profile = OrganizerProfile.for_user(self.organizer)
        self.assertTrue(profile.is_ambassador)
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, AmbassadorApplication.Status.APPROVED)
        self.assertIsNotNone(self.application.reviewed_at)

    def test_reject_does_not_grant_ambassador_status(self):
        self.application.reject(note="Document illisible")

        profile = OrganizerProfile.for_user(self.organizer)
        self.assertFalse(profile.is_ambassador)
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, AmbassadorApplication.Status.REJECTED)
        self.assertEqual(self.application.admin_note, "Document illisible")

    def test_admin_delete_documents_action_clears_rejected_file_only(self):
        self.application.reject()
        pending = AmbassadorApplication.objects.create(
            organizer=get_user_model().objects.create_user(username="autre", password="secret"),
            id_document_number="CD7654321",
            id_document_file=_make_image_file(),
        )
        admin_user = get_user_model().objects.create_superuser(
            username="admin-identite", email="admin@example.com", password="secret"
        )
        self.client.force_login(admin_user)

        response = self.client.post(
            reverse("admin:accounts_ambassadorapplication_changelist"),
            {
                "action": "delete_documents",
                "_selected_action": [str(self.application.pk), str(pending.pk)],
            },
        )

        self.assertEqual(response.status_code, 302)
        self.application.refresh_from_db()
        pending.refresh_from_db()
        self.assertFalse(self.application.id_document_file)
        self.assertTrue(pending.id_document_file)
