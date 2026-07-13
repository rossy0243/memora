from django.db import connection, transaction

try:
    from botocore.exceptions import BotoCoreError, ClientError
except ImportError:  # pragma: no cover - botocore is installed with S3 storage in prod.
    BotoCoreError = ClientError = ()


STORAGE_UNAVAILABLE_MESSAGE = (
    "Le stockage des medias est momentanement indisponible. "
    "Reessayez dans quelques minutes."
)


def is_storage_error(exc):
    return isinstance(exc, (BotoCoreError, ClientError, OSError))


def recover_from_storage_error():
    if connection.in_atomic_block and connection.needs_rollback:
        transaction.set_rollback(False)
