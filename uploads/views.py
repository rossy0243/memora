import logging

from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from core.storage_errors import STORAGE_UNAVAILABLE_MESSAGE, is_storage_error, recover_from_storage_error
from events.access import has_guest_access
from events.models import Event

from .forms import GuestUploadForm
from .services import ensure_session_key, get_client_ip, get_upload_limit_error, get_upload_quota


logger = logging.getLogger(__name__)


def guest_upload_create(request, slug, access_key):
    event = get_object_or_404(Event, slug=slug, public_access_key=access_key, is_active=True)
    if not has_guest_access(request, event):
        return redirect(event.get_public_url())

    session_key = ensure_session_key(request)
    upload_quota = get_upload_quota(event, session_key)

    if request.method == "POST":
        form = GuestUploadForm(request.POST, request.FILES, event=event)
        if form.is_valid():
            ip_address = get_client_ip(request)
            limit_error = get_upload_limit_error(event, session_key, ip_address)

            if limit_error:
                logger.warning("Guest upload blocked for event=%s reason=%s", event.pk, limit_error)
                form.add_error(None, limit_error)
            else:
                media_file = form.cleaned_data["media_file"]
                upload = form.save(commit=False)
                upload.event = event
                upload.media_type = GuestUploadForm.get_media_type(media_file.name)
                upload.original_filename = media_file.name
                upload.file_size = media_file.size
                upload.duration = form.media_duration
                upload.ip_address = ip_address
                upload.user_agent = request.META.get("HTTP_USER_AGENT", "")[:1000]
                upload.session_key = session_key
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
                    return redirect(
                        reverse(
                            "uploads:thanks",
                            kwargs={
                                "slug": event.slug,
                                "access_key": event.public_access_key,
                            },
                        )
                    )
    else:
        form = GuestUploadForm(event=event)

    return render(
        request,
        "uploads/guest_upload_form.html",
        {
            "event": event,
            "form": form,
            "upload_quota": upload_quota,
        },
    )


def guest_upload_thanks(request, slug, access_key):
    event = get_object_or_404(Event, slug=slug, public_access_key=access_key, is_active=True)
    if not has_guest_access(request, event):
        return redirect(event.get_public_url())
    return render(request, "uploads/guest_upload_thanks.html", {"event": event})
