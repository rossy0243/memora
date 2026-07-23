from django.conf import settings
from django.db.models import F
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
