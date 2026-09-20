"""Reponses de telechargement rapides pour les fichiers volumineux (films, montages).

Sur R2, on ne fait PAS transiter le fichier par Django : on redirige le
navigateur vers une URL signee de courte duree, qui force l'enregistrement
(`Content-Disposition: attachment`). Le debit est alors celui de R2, et aucun
worker web (il n'y en a que deux) n'est immobilise pendant que 800 Mo passent.

Une simple balise `<a download>` ne suffit pas : l'attribut est ignore des que le
fichier est sur un autre domaine (R2), et le navigateur — surtout mobile — ouvre
alors la video dans l'onglet au lieu de la telecharger.
"""
from django.http import FileResponse, HttpResponse, HttpResponseRedirect
from storages.backends.s3 import S3Storage

from core.storage_errors import STORAGE_UNAVAILABLE_MESSAGE, is_storage_error, recover_from_storage_error

SIGNED_URL_LIFETIME_SECONDS = 3600


def _content_disposition(filename):
    return f'attachment; filename="{filename}"'


def download_response(field_file, filename, content_type="video/mp4"):
    storage = field_file.storage
    if isinstance(storage, S3Storage):
        url = storage.url(
            field_file.name,
            parameters={
                "ResponseContentDisposition": _content_disposition(filename),
                "ResponseContentType": content_type,
            },
            expire=SIGNED_URL_LIFETIME_SECONDS,
        )
        response = HttpResponseRedirect(url)
        # L'URL signee est personnelle et temporaire : jamais mise en cache.
        response["Cache-Control"] = "private, no-store"
        return response

    try:
        field_file.open("rb")
    except Exception as exc:
        if not is_storage_error(exc):
            raise
        recover_from_storage_error()
        return HttpResponse(STORAGE_UNAVAILABLE_MESSAGE, status=503, content_type="text/plain")

    response = FileResponse(field_file, content_type=content_type)
    response["Content-Disposition"] = _content_disposition(filename)
    return response
