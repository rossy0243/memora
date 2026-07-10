from django.conf import settings
from django.core.checks import Error, register


@register()
def storage_configuration_check(app_configs, **kwargs):
    errors = []

    if settings.MEMORA_STORAGE_BACKEND not in {"local", "s3"}:
        errors.append(
            Error(
                "MEMORA_STORAGE_BACKEND doit valoir 'local' ou 's3'.",
                id="memora.E001",
            )
        )

    if settings.MEMORA_STORAGE_BACKEND == "s3":
        storage_options = settings.STORAGES.get("default", {}).get("OPTIONS", {})
        required_settings = {
            "MEMORA_S3_ACCESS_KEY_ID": storage_options.get("access_key"),
            "MEMORA_S3_SECRET_ACCESS_KEY": storage_options.get("secret_key"),
            "MEMORA_S3_BUCKET_NAME": storage_options.get("bucket_name"),
        }
        for name, value in required_settings.items():
            if not value:
                errors.append(
                    Error(
                        f"{name} est requis quand MEMORA_STORAGE_BACKEND=s3.",
                        id="memora.E002",
                    )
                )

    return errors
