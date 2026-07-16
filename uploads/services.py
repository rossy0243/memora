from django.conf import settings
from django.utils import timezone

from .models import GuestUpload, UploadCategory, UploadCategoryTemplate


FALLBACK_UPLOAD_CATEGORIES = [
    ("ceremony", "Ceremonie", 1),
    ("arrival", "Arrivee", 2),
    ("cocktail", "Cocktail", 3),
    ("reception", "Reception", 4),
    ("speech", "Discours", 5),
    ("dancefloor", "Piste de danse", 6),
    ("cake", "Gateau", 7),
    ("funny", "Moment drole", 8),
    ("emotional", "Moment emouvant", 9),
    ("other", "Autre", 10),
]


def create_default_categories_for_event(event):
    templates = list(
        UploadCategoryTemplate.objects.filter(
            event_type=event.event_type,
            is_active=True,
        ).order_by("sort_order", "label")
    )

    if not templates:
        templates = list(
            UploadCategoryTemplate.objects.filter(
                event_type__code="other",
                is_active=True,
            ).order_by("sort_order", "label")
        )

    categories = templates or [
        type("CategorySeed", (), {"code": code, "label": label, "sort_order": sort_order})
        for code, label, sort_order in FALLBACK_UPLOAD_CATEGORIES
    ]

    for category in categories:
        UploadCategory.objects.get_or_create(
            event=event,
            code=category.code,
            defaults={
                "label": category.label,
                "sort_order": category.sort_order,
                "is_active": True,
            },
        )


def get_client_ip(request):
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded_for:
        return forwarded_for.split(",")[-1].strip()
    return request.META.get("REMOTE_ADDR")


def ensure_session_key(request):
    if not request.session.session_key:
        request.session.create()
    return request.session.session_key


def get_upload_quota(event, session_key):
    limit = settings.MEMORA_SESSION_UPLOAD_LIMIT
    used = 0
    if session_key:
        used = GuestUpload.objects.filter(
            event=event,
            is_deleted=False,
            session_key=session_key,
        ).count()
    remaining = max(limit - used, 0)
    return {
        "limit": limit,
        "used": used,
        "remaining": remaining,
        "is_reached": remaining <= 0,
    }


def get_upload_limit_error(event, session_key, ip_address):
    event_uploads = GuestUpload.objects.filter(event=event, is_deleted=False)

    if event_uploads.count() >= settings.MEMORA_EVENT_UPLOAD_LIMIT:
        return "Cet evenement a deja atteint sa limite de souvenirs."

    if session_key and event_uploads.filter(session_key=session_key).count() >= settings.MEMORA_SESSION_UPLOAD_LIMIT:
        label = "souvenir" if settings.MEMORA_SESSION_UPLOAD_LIMIT == 1 else "souvenirs"
        return f"Vous avez atteint la limite de {settings.MEMORA_SESSION_UPLOAD_LIMIT} {label} pour cet evenement."

    if ip_address and event_uploads.filter(ip_address=ip_address).count() >= settings.MEMORA_IP_UPLOAD_LIMIT:
        return "Trop d'envois depuis cette connexion. Reessayez plus tard."

    cooldown_seconds = settings.MEMORA_UPLOAD_COOLDOWN_SECONDS
    if cooldown_seconds > 0:
        cooldown_after = timezone.now() - timezone.timedelta(seconds=cooldown_seconds)
        recent_uploads = event_uploads.filter(uploaded_at__gte=cooldown_after)

        if session_key and recent_uploads.filter(session_key=session_key).exists():
            return "Patientez quelques secondes avant d'envoyer un autre souvenir."

        if ip_address and recent_uploads.filter(ip_address=ip_address).exists():
            return "Patientez quelques secondes avant d'envoyer un autre souvenir."

    return ""
