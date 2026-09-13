"""Stockage dedie aux pieces d'identite des candidatures Ambassadeur.

Distinct du stockage par defaut (`STORAGES["default"]`, utilise pour les photos
et videos des invites) : celui-ci sert des documents sensibles (numero et scan
d'une piece d'identite). Quand `MEMORA_S3_CUSTOM_DOMAIN` est configure, le
stockage par defaut sert ses fichiers via un domaine public/CDN sans expiration
d'URL — parfait pour des souvenirs de mariage a partager, dangereux pour un
document d'identite. On force ici une URL signee et courte, sans jamais passer
par ce domaine public.
"""
import os

from django.conf import settings
from django.core.files.storage import Storage, default_storage


def identity_document_storage() -> Storage:
    """Storage a utiliser pour `AmbassadorApplication.id_document_file`.

    En S3/R2 : meme bucket et identifiants que le stockage par defaut, mais
    toujours des URL signees a duree de vie courte, jamais le domaine public.
    En stockage local (dev) : le storage par defaut convient (pas de domaine
    public a contourner).
    """
    if getattr(settings, "MEMORA_STORAGE_BACKEND", "local") != "s3":
        return default_storage

    from storages.backends.s3 import S3Storage

    return S3Storage(
        bucket_name=settings.MEMORA_S3_BUCKET_NAME,
        endpoint_url=settings.MEMORA_S3_ENDPOINT_URL,
        region_name=settings.MEMORA_S3_REGION_NAME,
        access_key=os.getenv("MEMORA_S3_ACCESS_KEY_ID", ""),
        secret_key=os.getenv("MEMORA_S3_SECRET_ACCESS_KEY", ""),
        addressing_style=os.getenv("MEMORA_S3_ADDRESSING_STYLE", "auto"),
        file_overwrite=False,
        querystring_auth=True,
        querystring_expire=300,
        custom_domain=None,
        default_acl=None,
    )
