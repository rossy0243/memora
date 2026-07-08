from django.conf import settings

from .models import GuestUpload, UploadCategory


DEFAULT_UPLOAD_CATEGORIES = [
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
    for code, label, sort_order in DEFAULT_UPLOAD_CATEGORIES:
        UploadCategory.objects.get_or_create(
            event=event,
            code=code,
            defaults={
                "label": label,
                "sort_order": sort_order,
                "is_active": True,
            },
        )


def get_client_ip(request):
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def ensure_session_key(request):
    if not request.session.session_key:
        request.session.create()
    return request.session.session_key


def get_upload_limit_error(event, session_key, ip_address):
    event_uploads = GuestUpload.objects.filter(event=event, is_deleted=False)

    if event_uploads.count() >= settings.MEMORA_EVENT_UPLOAD_LIMIT:
        return "Cet evenement a deja atteint sa limite de souvenirs."

    if session_key and event_uploads.filter(session_key=session_key).count() >= settings.MEMORA_SESSION_UPLOAD_LIMIT:
        return "Vous avez deja envoye beaucoup de souvenirs pour cet evenement."

    if ip_address and event_uploads.filter(ip_address=ip_address).count() >= settings.MEMORA_IP_UPLOAD_LIMIT:
        return "Trop d'envois depuis cette connexion. Reessayez plus tard."

    return ""
