from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from .checks import storage_configuration_check


class HomePageTests(SimpleTestCase):
    def test_home_page_returns_success(self):
        response = self.client.get(reverse("core:home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Memora")


class StorageConfigurationCheckTests(SimpleTestCase):
    @override_settings(MEMORA_STORAGE_BACKEND="local")
    def test_local_storage_configuration_is_valid(self):
        self.assertEqual(storage_configuration_check(None), [])

    @override_settings(MEMORA_STORAGE_BACKEND="ftp")
    def test_rejects_unknown_storage_backend(self):
        errors = storage_configuration_check(None)

        self.assertEqual(errors[0].id, "memora.E001")

    @override_settings(
        MEMORA_STORAGE_BACKEND="s3",
        STORAGES={
            "default": {
                "OPTIONS": {
                    "access_key": "",
                    "secret_key": "",
                    "bucket_name": "",
                }
            }
        },
    )
    def test_s3_storage_requires_credentials_and_bucket(self):
        errors = storage_configuration_check(None)

        self.assertEqual(len(errors), 3)
        self.assertTrue(all(error.id == "memora.E002" for error in errors))
