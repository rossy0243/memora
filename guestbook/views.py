import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.storage_errors import STORAGE_UNAVAILABLE_MESSAGE, is_storage_error, recover_from_storage_error

from .forms import GuestBookMessageForm
from .models import GuestBookAssignment
from .services import queue_guestbook_movie


logger = logging.getLogger(__name__)


def _require_agent(request):
    if not hasattr(request.user, "agent_profile"):
        raise Http404


def _get_assignment(request, pk):
    """La mission de CET agent sur cet evenement. Plusieurs agents peuvent en
    avoir chacun une, independamment : le service de l'un ne ferme pas celui
    des autres."""
    return get_object_or_404(
        GuestBookAssignment.objects.select_related("event"),
        event_id=pk,
        agent=request.user,
    )


@login_required
def agent_home(request):
    """Liste les missions livre d'or de l'agent connecte."""
    _require_agent(request)
    assignments = (
        GuestBookAssignment.objects.filter(agent=request.user)
        .select_related("event")
        .annotate(message_count=Count("event__guestbook_messages"))
        .order_by("-event__event_date")
    )
    return render(request, "guestbook/agent_home.html", {"assignments": assignments})


@login_required
def guestbook_capture(request, pk):
    _require_agent(request)
    assignment = _get_assignment(request, pk)
    event = assignment.event

    if assignment.ended_at:
        return render(request, "guestbook/shift_closed.html", {"event": event})

    if not assignment.started_at:
        assignment.started_at = timezone.now()
        assignment.save(update_fields=["started_at", "updated_at"])

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

    recorded = event.guestbook_messages.select_related("recorded_by").order_by("-created_at")
    return render(
        request,
        "guestbook/capture.html",
        {
            "event": event,
            "form": form,
            "max_duration_seconds": settings.MEMORA_GUESTBOOK_MAX_VIDEO_DURATION_SECONDS,
            "sent_count": recorded.count(),
            "recent_messages": recorded[:4],
        },
    )


@login_required
@require_POST
def end_shift(request, pk):
    _require_agent(request)
    assignment = _get_assignment(request, pk)
    assignment.ended_at = timezone.now()
    assignment.save(update_fields=["ended_at", "updated_at"])

    # Fin de service = declencheur normal du montage integral du livre d'or.
    # D'autres agents peuvent continuer a enregistrer sur le meme evenement :
    # le montage sera regenere a leur propre fin de service.
    if queue_guestbook_movie(assignment.event, trigger="agent_end_shift"):
        messages.success(
            request,
            "Service terminé. Le montage du livre d'or est lancé, "
            "l'organisateur le recevra dès qu'il est prêt.",
        )
    else:
        messages.success(request, "Service terminé. Merci pour cette mission !")
    return redirect("guestbook:agent_home")
