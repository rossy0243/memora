import logging
from io import BytesIO

import qrcode
from django.conf import settings
from django.core.mail import send_mail
from django.db.models import Count
from django.db.models.functions import TruncHour
from django.urls import reverse
from django.utils import timezone

logger = logging.getLogger(__name__)


def _event_dashboard_url(event):
    path = reverse("events:detail", kwargs={"pk": event.pk})
    base_url = settings.MEMORA_PUBLIC_BASE_URL.rstrip("/")
    if not base_url:
        return path
    return f"{base_url}{path}"


def send_payment_receipt_email(event):
    """Envoie un recu de paiement a l'organisateur apres confirmation en admin.

    Idempotent (receipt_sent_at) : relancer l'action admin sur un evenement deja
    marque paye ne renvoie pas un second recu. Echec silencieux (log) plutot que
    faire echouer l'action admin — meme raisonnement que notify_generated_movie_ready
    cote traitement des films.
    """
    if event.receipt_sent_at or not event.organizer.email or not event.is_paid:
        return False

    dashboard_url = _event_dashboard_url(event)
    lines = [
        "Bonjour,",
        "",
        f"Nous confirmons la réception de votre paiement pour l'événement « {event.title} ».",
        "",
        f"Montant réglé : {event.formatted_price}",
    ]
    if event.payment_reference:
        lines.append(f"Référence : {event.payment_reference}")
    lines += [
        f"Date : {(event.paid_at or timezone.now()):%d/%m/%Y}",
        "",
        f"Votre événement est désormais actif, vous pouvez le retrouver ici :\n{dashboard_url}",
        "",
        "Merci de votre confiance.",
        "",
        "L'équipe Memora",
    ]

    try:
        send_mail(
            subject=f"Reçu de paiement Memora - {event.title}",
            message="\n".join(lines),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[event.organizer.email],
            fail_silently=False,
        )
    except Exception:
        logger.exception("Payment receipt email failed event=%s", event.pk)
        return False

    event.receipt_sent_at = timezone.now()
    event.save(update_fields=["receipt_sent_at", "updated_at"])
    logger.info("Payment receipt email sent event=%s", event.pk)
    return True


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


def _drop_file(event, instance, field_name):
    """Supprime un fichier du stockage (R2). False s'il n'y en avait pas ou si le stockage refuse."""
    import logging

    field = getattr(instance, field_name, None)
    if not field:
        return False
    try:
        field.delete(save=False)
    except Exception as exc:  # storage indisponible : on n'interrompt pas
        logging.getLogger(__name__).warning(
            "drop file failed event=%s pk=%s field=%s error=%s",
            event.pk, getattr(instance, "pk", "?"), field_name, exc,
        )
        return False
    return True


class EventResetRefused(Exception):
    """La remise a zero n'est permise que pour un evenement en mode test invites."""


def reset_event_content(event):
    """Vide le CONTENU d'un evenement de test : l'evenement et son QR code restent intacts.

    Supprime souvenirs des invites, films generes, messages et montage du livre d'or
    (fichiers R2 puis lignes) et remet a zero les missions des agents. Conserve
    l'evenement lui-meme : lien et cle d'acces (donc le QR code), titre, date, couverture,
    musique, formule, paiement, moments et agents affectes.

    Securite : refuse tout evenement qui n'est pas en mode test invites, pour ne jamais
    effacer par erreur les souvenirs d'un vrai evenement.
    """
    from django.db import transaction

    if not event.guest_preview_enabled:
        raise EventResetRefused(
            "Par securite, seul un evenement en mode test invites peut etre vide. "
            "Activez d'abord « Activer pour test »."
        )

    counts = {
        "uploads": event.guest_uploads.count(),
        "movies": event.generated_movies.count(),
        "guestbook_messages": event.guestbook_messages.count(),
        "guestbook_movie": 0,
        "files": 0,
    }

    for upload in event.guest_uploads.all().iterator():
        counts["files"] += _drop_file(event, upload, "media_file")
    for movie in event.generated_movies.all().iterator():
        for field_name in ("final_file", "full_file", "teaser_file"):
            counts["files"] += _drop_file(event, movie, field_name)
    for message in event.guestbook_messages.all().iterator():
        counts["files"] += _drop_file(event, message, "media_file")
    montage = getattr(event, "guestbook_movie", None)
    if montage:
        counts["guestbook_movie"] = 1
        for field_name in ("final_file", "light_file"):
            counts["files"] += _drop_file(event, montage, field_name)

    with transaction.atomic():
        # Uploads avant tout : GuestUpload.category est un FK PROTECT (voir delete_event).
        event.guest_uploads.all().delete()
        event.generated_movies.all().delete()
        event.guestbook_messages.all().delete()
        if montage:
            montage.delete()
        event.guestbook_assignments.update(started_at=None, ended_at=None)

    import logging

    logging.getLogger(__name__).info("reset_event_content event=%s counts=%s", event.pk, counts)
    return counts


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
        return _drop_file(event, instance, field_name)

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
            for field_name in ("final_file", "light_file"):
                if drop(montage, field_name):
                    counts["deliverables"] += 1
                setattr(montage, field_name, "")
            montage.media_purged = True
            montage.save(update_fields=["final_file", "light_file", "media_purged"])

    # La chanson televersee par l'organisateur est un fichier a lui : elle part avec
    # l'evenement, comme la couverture et le QR code.
    event_fields = ("cover_image", "qr_code_image", "custom_music_file")
    for field_name in event_fields:
        if drop(event, field_name):
            counts["event"] += 1
            setattr(event, field_name, "")
    if counts["event"]:
        event.save(update_fields=[*event_fields, "updated_at"])

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
