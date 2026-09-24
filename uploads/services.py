from django.conf import settings
import re
import secrets

from django.db.models import F, Max, Q
from django.utils import timezone
from django.utils.text import slugify

from core.security import get_client_ip

from .models import GuestUpload, MomentTemplate, UploadCategory, UploadCategoryTemplate


FALLBACK_UPLOAD_CATEGORIES = [
    ("ceremony", "Cérémonie", 1),
    ("arrival", "Arrivée", 2),
    ("cocktail", "Cocktail", 3),
    ("reception", "Réception", 4),
    ("speech", "Discours", 5),
    ("dancefloor", "Piste de danse", 6),
    ("cake", "Gâteau", 7),
    ("funny", "Moment drôle", 8),
    ("emotional", "Moment émouvant", 9),
    ("other", "Autre", 10),
]


def normalize_moment_label(value):
    normalized = " ".join((value or "").strip().split())[:80]
    if normalized.islower() or normalized.isupper():
        return normalized.capitalize()
    return normalized


def moment_code_from_label(label):
    return slugify(label)[:40] or "moment"


def get_or_create_moment_template(label, user=None, status=None, suggested_event_type=None, code=None):
    normalized_label = normalize_moment_label(label)
    if not normalized_label:
        return None

    code = code or moment_code_from_label(normalized_label)
    defaults = {
        "label": normalized_label,
        "status": status or MomentTemplate.ModerationStatus.PENDING,
        "is_active": True,
    }
    if user and getattr(user, "is_authenticated", False):
        defaults["created_by"] = user

    moment, created = MomentTemplate.objects.get_or_create(code=code, defaults=defaults)
    if suggested_event_type:
        moment.suggested_event_types.add(suggested_event_type)
    return moment


def ensure_moment_templates_from_category_templates():
    for template in UploadCategoryTemplate.objects.select_related("event_type"):
        get_or_create_moment_template(
            template.label,
            status=MomentTemplate.ModerationStatus.APPROVED,
            suggested_event_type=template.event_type,
            code=template.code,
        )


def get_available_moment_templates():
    ensure_moment_templates_from_category_templates()
    return MomentTemplate.objects.filter(
        is_active=True,
        status=MomentTemplate.ModerationStatus.APPROVED,
    ).order_by("-usage_count", "label")


def get_default_moment_templates_for_event_type(event_type):
    ensure_moment_templates_from_category_templates()
    templates = list(
        UploadCategoryTemplate.objects.filter(
            event_type=event_type,
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

    moments = []
    seen_codes = set()
    for template in templates:
        moment = get_or_create_moment_template(
            template.label,
            status=MomentTemplate.ModerationStatus.APPROVED,
            suggested_event_type=template.event_type,
            code=template.code,
        )
        if moment and moment.code not in seen_codes:
            moments.append(moment)
            seen_codes.add(moment.code)
    return moments


def get_event_type_moment_suggestions():
    suggestions = {}
    for template in UploadCategoryTemplate.objects.select_related("event_type").filter(is_active=True):
        moment = get_or_create_moment_template(
            template.label,
            status=MomentTemplate.ModerationStatus.APPROVED,
            suggested_event_type=template.event_type,
            code=template.code,
        )
        if moment:
            suggestions.setdefault(str(template.event_type_id), []).append(str(moment.pk))
    return suggestions


def resolve_moment_values(values, event_type=None, user=None):
    moments = []
    seen_codes = set()
    for raw_value in values or []:
        value = str(raw_value or "").strip()
        if not value:
            continue

        moment = None
        if value.isdigit():
            moment = MomentTemplate.objects.filter(pk=int(value), is_active=True).first()
        elif value.startswith("new:"):
            moment = get_or_create_moment_template(value[4:], user=user)
        else:
            moment = get_or_create_moment_template(value, user=user)

        if not moment or moment.status == MomentTemplate.ModerationStatus.REJECTED:
            continue
        if event_type:
            moment.suggested_event_types.add(event_type)
        if moment.code in seen_codes:
            continue
        moments.append(moment)
        seen_codes.add(moment.code)
    return moments


def register_moment_usage(moment):
    MomentTemplate.objects.filter(pk=moment.pk).update(usage_count=F("usage_count") + 1)
    moment.refresh_from_db(fields=["usage_count", "status", "auto_promoted_at"])
    threshold = settings.MEMORA_MOMENT_AUTO_PROMOTION_USAGE_THRESHOLD
    if (
        moment.status == MomentTemplate.ModerationStatus.PENDING
        and threshold > 0
        and moment.usage_count >= threshold
    ):
        moment.status = MomentTemplate.ModerationStatus.APPROVED
        moment.auto_promoted_at = timezone.now()
        moment.save(update_fields=["status", "auto_promoted_at", "updated_at"])


def sync_event_upload_categories(event, moment_values=None, user=None, count_all_usage=False):
    moments = resolve_moment_values(moment_values, event_type=event.event_type, user=user)
    if not moments:
        moments = get_default_moment_templates_for_event_type(event.event_type)

    selected_codes = [moment.code for moment in moments]
    UploadCategory.objects.filter(event=event).exclude(code__in=selected_codes).update(is_active=False)

    for index, moment in enumerate(moments, start=1):
        category, created = UploadCategory.objects.update_or_create(
            event=event,
            code=moment.code,
            defaults={
                "label": moment.label,
                "sort_order": index,
                "is_active": True,
            },
        )
        if created or count_all_usage:
            register_moment_usage(moment)


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


def get_or_create_default_upload_category(event):
    """Categorie fourre-tout assignee automatiquement : l'invite ne choisit plus de moment."""
    category = event.upload_categories.filter(code="other").first()
    if category:
        if not category.is_active:
            category.is_active = True
            category.save(update_fields=["is_active"])
        return category

    last_sort_order = event.upload_categories.aggregate(Max("sort_order"))["sort_order__max"] or 0
    return UploadCategory.objects.create(
        event=event,
        code="other",
        label="Autre",
        sort_order=last_sort_order + 1,
        is_active=True,
    )


def ensure_session_key(request):
    if not request.session.session_key:
        request.session.create()
    return request.session.session_key


DEVICE_COOKIE_NAME = "memora_device"
DEVICE_COOKIE_MAX_AGE = 60 * 60 * 24 * 365
_DEVICE_TOKEN = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
_DEVICE_SIGNATURE = re.compile(r"^[0-9a-f]{8,32}$")


def _clean(value, pattern):
    value = (value or "").strip()
    return value if pattern.match(value) else ""


def get_device_identity(request):
    """Ce qui permet de reconnaitre un invite : cookie de session, cookie d'appareil pose par le
    serveur, identifiant garde par la page (stockage du navigateur) et empreinte materielle.

    L'empreinte est seulement enregistree (des telephones identiques la partagent) : elle ne bloque
    personne, elle permet de reperer un abus apres coup."""
    cookie_id = _clean(request.COOKIES.get(DEVICE_COOKIE_NAME), _DEVICE_TOKEN)
    return {
        "device_cookie": cookie_id or secrets.token_urlsafe(24),
        "is_new_cookie": not cookie_id,
        "device_id": _clean(request.POST.get("device_id"), _DEVICE_TOKEN),
        "device_signature": _clean(request.POST.get("device_sig"), _DEVICE_SIGNATURE),
    }


def remember_device(response, identity):
    if identity["is_new_cookie"]:
        response.set_cookie(
            DEVICE_COOKIE_NAME,
            identity["device_cookie"],
            max_age=DEVICE_COOKIE_MAX_AGE,
            httponly=True,
            samesite="Lax",
            secure=settings.SESSION_COOKIE_SECURE,
        )
    return response


def _guest_uploads(event, session_key, identity):
    """Les souvenirs deja envoyes par CET invite : meme session OU meme appareil (cookie serveur ou
    identifiant du navigateur). Vider ses cookies ne remet donc plus le compteur a zero."""
    uploads = GuestUpload.objects.filter(event=event, is_deleted=False)
    identity = identity or {}
    match = Q(pk__in=[])
    if session_key:
        match |= Q(session_key=session_key)
    if identity.get("device_cookie"):
        match |= Q(device_cookie=identity["device_cookie"])
    if identity.get("device_id"):
        match |= Q(device_id=identity["device_id"])
    return uploads.filter(match)


def get_upload_quota(event, session_key, identity=None):
    limit = settings.MEMORA_SESSION_UPLOAD_LIMIT
    used = _guest_uploads(event, session_key, identity).count()
    remaining = max(limit - used, 0)
    return {
        "limit": limit,
        "used": used,
        "remaining": remaining,
        "is_reached": remaining <= 0,
    }


def get_upload_limit_error(event, session_key, ip_address, identity=None):
    event_uploads = GuestUpload.objects.filter(event=event, is_deleted=False)

    # Quota de la formule, avec marge de tolerance : on ne bloque jamais un invite
    # « en trop » — la limite porte sur le nombre de souvenirs, pas sur les
    # personnes — et le depassement leger passe quand meme.
    if event_uploads.count() >= event.upload_hard_limit:
        return (
            "Cet événement a atteint le nombre de souvenirs inclus dans sa formule. "
            "L'organisateur peut passer à une formule supérieure pour en collecter plus."
        )

    guest_uploads = _guest_uploads(event, session_key, identity)
    if guest_uploads.count() >= settings.MEMORA_SESSION_UPLOAD_LIMIT:
        label = "souvenir" if settings.MEMORA_SESSION_UPLOAD_LIMIT == 1 else "souvenirs"
        return f"Vous avez atteint la limite de {settings.MEMORA_SESSION_UPLOAD_LIMIT} {label} pour cet événement."

    if ip_address and event_uploads.filter(ip_address=ip_address).count() >= settings.MEMORA_IP_UPLOAD_LIMIT:
        return "Trop d'envois depuis cette connexion. Réessayez plus tard."

    cooldown_seconds = settings.MEMORA_UPLOAD_COOLDOWN_SECONDS
    if cooldown_seconds > 0:
        cooldown_after = timezone.now() - timezone.timedelta(seconds=cooldown_seconds)
        if guest_uploads.filter(uploaded_at__gte=cooldown_after).exists():
            return "Patientez quelques secondes avant d'envoyer un autre souvenir."

        # Pas de pause par adresse IP : tous les invites d'une meme salle (Wi-Fi du lieu, reseau mobile
        # partage par l'operateur) partagent la meme adresse, et une pause commune limiterait TOUTE la
        # salle a un souvenir toutes les 8 s. La pause est donc par invite (cookie de session) seulement.

    return ""
