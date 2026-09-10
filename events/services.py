from io import BytesIO

import qrcode
from django.db.models import Count
from django.db.models.functions import TruncHour
from django.utils import timezone


def build_event_qr_code_png(public_url):
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=12,
        border=2,
    )
    qr.add_data(public_url)
    qr.make(fit=True)

    image = qr.make_image(fill_color="#241f22", back_color="#fffaf7").convert("RGB")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def build_hourly_upload_breakdown(uploads_queryset):
    """Souvenirs recus par heure locale, pour donner un pouls de la soiree.

    Remplace l'ancienne repartition par moment : depuis que les invites ne
    choisissent plus de moment, ce decoupage serait redondant (tout tombe
    dans une categorie unique) alors que l'horaire, lui, reste significatif.
    """
    rows = (
        uploads_queryset.annotate(hour=TruncHour("uploaded_at", tzinfo=timezone.get_current_timezone()))
        .values("hour")
        .annotate(count=Count("id"))
        .order_by("hour")
    )
    return list(rows)


def build_readiness_checklist(event):
    """Etat de preparation avant le jour J : ne s'appuie que sur des champs
    deja stockes, sans tracking ni migration supplementaire.
    """
    items = [
        {
            "label": "Paiement validé",
            "is_done": event.is_paid,
            "is_required": True,
            "hint": "L'administrateur doit valider le paiement pour ouvrir la collecte aux invités.",
        },
        {
            "label": "Collecte active",
            "is_done": event.is_active,
            "is_required": True,
            "hint": "L'événement est actuellement fermé : réactivez-le pour que le QR code fonctionne.",
        },
        {
            "label": "Message d'accueil personnalisé",
            "is_done": bool(event.welcome_message.strip()),
            "is_required": False,
            "hint": "Ajoutez un mot pour vos invités : il apparaît sur l'écran de capture.",
        },
        {
            "label": "Photo de couverture ajoutée",
            "is_done": bool(event.cover_image),
            "is_required": False,
            "hint": "Une photo personnalise la page invité et l'écran de capture.",
        },
    ]
    is_ready = all(item["is_done"] for item in items if item["is_required"])
    return {"items": items, "is_ready": is_ready}


def generate_event_qr_code(event, public_url):
    """Legacy helper kept for existing callers/tests that still need stored QR files."""
    from django.core.files.base import ContentFile

    png_bytes = build_event_qr_code_png(public_url)
    filename = f"{event.slug}-qr.png"
    if event.qr_code_image:
        event.qr_code_image.delete(save=False)
    event.qr_code_image.save(filename, ContentFile(png_bytes), save=False)
    event.save(update_fields=["qr_code_image", "updated_at"])
    return event.qr_code_image


def purge_event_media(event, *, include_deliverables=True):
    """Supprime de R2 tous les fichiers rattaches a un evenement.

    Rend un dict {categorie: nombre de fichiers supprimes}. Marque les lignes
    concernees comme purgees (media_purged) mais ne supprime aucune ligne : le
    seul appelant qui supprime des lignes est la suppression d'evenement de
    l'admin, ou la cascade s'en charge apres cet appel.
    """
    import logging

    logger = logging.getLogger(__name__)
    counts = {"uploads": 0, "guestbook": 0, "deliverables": 0, "event": 0}

    def drop(instance, field_name):
        field = getattr(instance, field_name, None)
        if not field:
            return False
        try:
            field.delete(save=False)
        except Exception as exc:  # storage indisponible : on n'interrompt pas
            logger.warning(
                "purge_event_media failed event=%s pk=%s field=%s error=%s",
                event.pk, getattr(instance, "pk", "?"), field_name, exc,
            )
            return False
        return True

    for upload in event.guest_uploads.exclude(media_file=""):
        if drop(upload, "media_file"):
            counts["uploads"] += 1
        upload.media_file = ""
        upload.is_deleted = True
        upload.media_purged = True
        upload.save(update_fields=["media_file", "is_deleted", "media_purged"])

    for message in event.guestbook_messages.exclude(media_file=""):
        if drop(message, "media_file"):
            counts["guestbook"] += 1
        message.media_file = ""
        message.media_purged = True
        message.save(update_fields=["media_file", "media_purged"])

    if include_deliverables:
        for movie in event.generated_movies.filter(media_purged=False):
            for field_name in ("final_file", "full_file", "teaser_file"):
                if drop(movie, field_name):
                    counts["deliverables"] += 1
                setattr(movie, field_name, "")
            movie.media_purged = True
            movie.save(update_fields=["final_file", "full_file", "teaser_file", "media_purged"])

        montage = getattr(event, "guestbook_movie", None)
        if montage and not montage.media_purged:
            if drop(montage, "final_file"):
                counts["deliverables"] += 1
            montage.final_file = ""
            montage.media_purged = True
            montage.save(update_fields=["final_file", "media_purged"])

    for field_name in ("cover_image", "qr_code_image"):
        if drop(event, field_name):
            counts["event"] += 1
            setattr(event, field_name, "")
    if counts["event"]:
        event.save(update_fields=["cover_image", "qr_code_image", "updated_at"])

    logger.info("purge_event_media event=%s counts=%s", event.pk, counts)
    return counts


def delete_event(event):
    """Supprime completement un evenement : fichiers R2 puis lignes.

    On efface d'abord les uploads invites : `GuestUpload.category` est un FK
    PROTECT vers `UploadCategory`, que la cascade de l'evenement supprimerait —
    sans cet ordre, Django leverait ProtectedError.
    """
    counts = purge_event_media(event)
    event.guest_uploads.all().delete()
    event.delete()
    return counts
