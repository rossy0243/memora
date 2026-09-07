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
