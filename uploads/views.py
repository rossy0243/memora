import logging

from django.core.cache import cache
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.storage_errors import STORAGE_UNAVAILABLE_MESSAGE, is_storage_error, recover_from_storage_error
from events.access import has_guest_access, upcoming_event_response
from events.models import Event

from .forms import GuestUploadForm
from .services import (
    ensure_session_key,
    get_client_ip,
    get_device_identity,
    get_or_create_default_upload_category,
    get_upload_limit_error,
    get_upload_quota,
    remember_device,
)


logger = logging.getLogger(__name__)


def guest_upload_create(request, slug, access_key):
    event = get_object_or_404(Event, slug=slug, public_access_key=access_key)
    if not event.can_accept_guest_uploads:
        return render(request, "events/public_event_unavailable.html", {"event": event}, status=403)
    upcoming = upcoming_event_response(request, event)
    if upcoming:
        return upcoming
    if not has_guest_access(request, event):
        return redirect(event.get_public_url())

    session_key = ensure_session_key(request)
    identity = get_device_identity(request)
    upload_quota = get_upload_quota(event, session_key, identity)

    if request.method == "POST":
        form = GuestUploadForm(request.POST, request.FILES, event=event)
        if form.is_valid():
            ip_address = get_client_ip(request)
            limit_error = get_upload_limit_error(event, session_key, ip_address, identity)

            if limit_error:
                logger.warning("Guest upload blocked for event=%s reason=%s", event.pk, limit_error)
                form.add_error(None, limit_error)
            else:
                media_file = form.cleaned_data["media_file"]
                upload = form.save(commit=False)
                upload.event = event
                upload.category = get_or_create_default_upload_category(event)
                upload.media_type = GuestUploadForm.get_media_type(media_file.name)
                upload.original_filename = media_file.name
                upload.file_size = media_file.size
                upload.duration = form.media_duration
                upload.ip_address = ip_address
                upload.user_agent = request.META.get("HTTP_USER_AGENT", "")[:1000]
                upload.session_key = session_key
                upload.device_cookie = identity["device_cookie"]
                upload.device_id = identity["device_id"]
                upload.device_signature = identity["device_signature"]
                try:
                    upload.save()
                except Exception as exc:
                    if not is_storage_error(exc):
                        raise
                    logger.exception("Guest upload storage error for event=%s", event.pk)
                    recover_from_storage_error()
                    form.add_error("media_file", STORAGE_UNAVAILABLE_MESSAGE)
                else:
                    logger.info("Guest upload accepted event=%s upload=%s type=%s", event.pk, upload.pk, upload.media_type)
                    return remember_device(
                        redirect(
                            reverse(
                                "uploads:thanks",
                                kwargs={
                                    "slug": event.slug,
                                    "access_key": event.public_access_key,
                                },
                            )
                        ),
                        identity,
                    )
    else:
        form = GuestUploadForm(event=event)

    return remember_device(
        render(
            request,
            "uploads/guest_upload_form.html",
            {
                "event": event,
                "form": form,
                "upload_quota": upload_quota,
                # Un point par souvenir permis ; au-dela de 8, le texte suffit.
                "quota_slots": range(upload_quota["limit"]) if upload_quota["limit"] <= 8 else [],
            },
        ),
        identity,
    )


def guest_upload_thanks(request, slug, access_key):
    event = get_object_or_404(Event, slug=slug, public_access_key=access_key)
    if not event.can_accept_guest_uploads:
        return render(request, "events/public_event_unavailable.html", {"event": event}, status=403)
    upcoming = upcoming_event_response(request, event)
    if upcoming:
        return upcoming
    if not has_guest_access(request, event):
        return redirect(event.get_public_url())
    return render(request, "uploads/guest_upload_thanks.html", {"event": event})


@require_POST
def preview_diagnostic(request, slug, access_key):
    """Rapport technique anonyme quand un telephone ne relit pas son propre enregistrement.

    Sert a comprendre les cas rares (formats video de certains iPhone) : une ligne de log,
    au plus quelques rapports par heure et par adresse, rien de personnel.
    """
    event = get_object_or_404(Event, slug=slug, public_access_key=access_key)
    if not has_guest_access(request, event):
        return HttpResponse(status=403)
    throttle_key = f"preview-diagnostic:{get_client_ip(request)}"
    count = cache.get(throttle_key, 0)
    if count < 10:
        cache.set(throttle_key, count + 1, 3600)
        logger.warning("Guest preview diagnostic event=%s report=%s", event.pk, request.POST.get("report", "")[:2000])
    return HttpResponse(status=204)
