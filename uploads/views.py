from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from events.models import Event

from .forms import GuestUploadForm
from .services import ensure_session_key, get_client_ip, get_upload_limit_error


def guest_upload_create(request, slug):
    event = get_object_or_404(Event, slug=slug, is_active=True)

    if request.method == "POST":
        form = GuestUploadForm(request.POST, request.FILES, event=event)
        if form.is_valid():
            session_key = ensure_session_key(request)
            ip_address = get_client_ip(request)
            limit_error = get_upload_limit_error(event, session_key, ip_address)

            if limit_error:
                form.add_error(None, limit_error)
            else:
                media_file = form.cleaned_data["media_file"]
                upload = form.save(commit=False)
                upload.event = event
                upload.media_type = GuestUploadForm.get_media_type(media_file.name)
                upload.original_filename = media_file.name
                upload.file_size = media_file.size
                upload.ip_address = ip_address
                upload.user_agent = request.META.get("HTTP_USER_AGENT", "")[:1000]
                upload.session_key = session_key
                upload.save()
                return redirect(reverse("uploads:thanks", kwargs={"slug": event.slug}))
    else:
        form = GuestUploadForm(event=event)

    return render(request, "uploads/guest_upload_form.html", {"event": event, "form": form})


def guest_upload_thanks(request, slug):
    event = get_object_or_404(Event, slug=slug, is_active=True)
    return render(request, "uploads/guest_upload_thanks.html", {"event": event})
