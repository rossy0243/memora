import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.storage_errors import STORAGE_UNAVAILABLE_MESSAGE, is_storage_error, recover_from_storage_error
from events.models import Event

from .forms import GuestBookMessageForm


logger = logging.getLogger(__name__)


def _require_agent(request):
    if not hasattr(request.user, "agent_profile"):
        raise Http404


def _get_assigned_event(request, pk):
    return get_object_or_404(Event, pk=pk, guestbook_agent=request.user)


@login_required
def agent_home(request):
    """Liste les missions livre d'or de l'agent connecte."""
    _require_agent(request)
    missions = Event.objects.filter(guestbook_agent=request.user).order_by("-event_date")
    return render(request, "guestbook/agent_home.html", {"missions": missions})


@login_required
def guestbook_capture(request, pk):
    _require_agent(request)
    event = _get_assigned_event(request, pk)

    if event.guestbook_ended_at:
        return render(request, "guestbook/shift_closed.html", {"event": event})

    if not event.guestbook_started_at:
        event.guestbook_started_at = timezone.now()
        event.save(update_fields=["guestbook_started_at", "updated_at"])

    if request.method == "POST":
        form = GuestBookMessageForm(request.POST, request.FILES)
        if form.is_valid():
            media_file = form.cleaned_data["media_file"]
            message = form.save(commit=False)
            message.event = event
            message.original_filename = media_file.name
            message.file_size = media_file.size
            message.duration = form.media_duration
            message.recorded_by = request.user
            try:
                message.save()
            except Exception as exc:
                if not is_storage_error(exc):
                    raise
                logger.exception("Guestbook storage error for event=%s", event.pk)
                recover_from_storage_error()
                form.add_error("media_file", STORAGE_UNAVAILABLE_MESSAGE)
            else:
                logger.info("Guestbook message recorded event=%s message=%s", event.pk, message.pk)
                messages.success(request, "Message enregistré. Au suivant !")
                return redirect("guestbook:capture", pk=event.pk)
    else:
        form = GuestBookMessageForm()

    return render(
        request,
        "guestbook/capture.html",
        {
            "event": event,
            "form": form,
            "max_duration_seconds": settings.MEMORA_GUESTBOOK_MAX_VIDEO_DURATION_SECONDS,
        },
    )


@login_required
@require_POST
def end_shift(request, pk):
    _require_agent(request)
    event = _get_assigned_event(request, pk)
    event.guestbook_ended_at = timezone.now()
    event.save(update_fields=["guestbook_ended_at", "updated_at"])
    messages.success(request, "Service terminé. Merci pour cette mission !")
    return redirect("guestbook:agent_home")
