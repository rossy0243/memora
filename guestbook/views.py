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
from events.models import Event

from .forms import GuestBookMessageForm
from .models import GuestBookAssignment, RemoteGuestbookCode
from .services import has_open_shifts, queue_guestbook_movie


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

    # Le stand n'ouvre que le jour J (l'equipe peut avancer la date pour un essai avec
    # « Activer pour test », meme reglage que le parcours invite : event.is_upcoming_for_agent le
    # prend en compte). Sans ce garde-fou, un agent qui ouvre sa mission en avance
    # enregistre des messages de test qui se retrouveraient dans le montage final.
    if event.is_upcoming_for_agent:
        return render(request, "guestbook/mission_not_started.html", {"event": event})

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

    # Fin de service = declencheur normal du montage integral du livre d'or, mais seulement pour le
    # DERNIER agent : tant qu'un autre enregistre encore, lancer le montage en produirait une version
    # partielle (visible trop tot) et ses derniers messages risqueraient de ne pas y figurer.
    if has_open_shifts(assignment.event):
        messages.success(
            request,
            "Service terminé. Le montage du livre d'or démarrera quand les autres agents "
            "auront terminé leur service.",
        )
    elif queue_guestbook_movie(assignment.event, trigger="agent_end_shift"):
        messages.success(
            request,
            "Service terminé. Le montage du livre d'or est lancé, "
            "l'organisateur le recevra dès qu'il est prêt.",
        )
    else:
        messages.success(request, "Service terminé. Merci pour cette mission !")
    return redirect("guestbook:agent_home")


def _remote_code_session_key(event):
    return f"memora_remote_code_{event.pk}"


def remote_capture(request, slug):
    """Livre d'or a distance : un lien connu de tous (pas secret), verrouille par un code a usage
    unique que l'organisateur genere et transmet lui-meme a un proche qui ne peut pas etre present.
    Une fois le code valide, meme camera que le stand ; meme table GuestBookMessage, meme secret que
    les messages enregistres par l'agent — l'organisateur ne voit jamais que le montage final."""
    event = get_object_or_404(Event, slug=slug)
    if not event.remote_guestbook_enabled or not event.can_accept_guest_uploads:
        return render(request, "events/public_event_unavailable.html", {"event": event}, status=403)

    # Contrairement au QR des invites sur place, pas de garde-fou "pas encore ouvert" : un proche
    # eloigne peut enregistrer des qu'il est disponible, meme avant le jour J. Seule limite : 22h00
    # le jour de l'evenement, annoncee sur la page pour que personne ne soit pris de court.
    if timezone.now() >= event.remote_guestbook_closes_at:
        return render(
            request,
            "guestbook/remote_code_entry.html",
            {"event": event, "closed": True, "closes_at": event.remote_guestbook_closes_at},
        )

    session_key = _remote_code_session_key(event)
    sent_key = f"{session_key}_sent"

    # Apres un envoi reussi, guestbook-capture.js recharge la MEME page en GET (comme au stand :
    # ecran pret pour le "suivant"). Le code est deja consomme a cet instant ; ce fanion, pose une
    # seule fois, permet d'afficher quand meme l'ecran de remerciement au lieu de redemander un code.
    if request.session.get(sent_key):
        del request.session[sent_key]
        return render(request, "guestbook/remote_capture.html", {"event": event, "sent": True})

    code = None
    code_id = request.session.get(session_key)
    if code_id:
        code = RemoteGuestbookCode.objects.filter(pk=code_id, event=event, used_at__isnull=True).first()
        if not code:
            del request.session[session_key]

    if not code:
        code_error = ""
        if request.method == "POST":
            entered = (request.POST.get("code") or "").strip().upper()
            code = RemoteGuestbookCode.objects.filter(event=event, code=entered, used_at__isnull=True).first()
            if code:
                request.session[session_key] = code.pk
                return redirect("guestbook_remote_capture", slug=slug)
            code_error = "Ce code n'est pas valide, ou il a déjà servi. Demandez-en un nouveau."
        return render(
            request,
            "guestbook/remote_code_entry.html",
            {"event": event, "code_error": code_error, "closes_at": event.remote_guestbook_closes_at},
        )

    sent = False
    if request.method == "POST":
        form = GuestBookMessageForm(request.POST, request.FILES, require_name=True)
        if form.is_valid():
            media_file = form.cleaned_data["media_file"]
            message = form.save(commit=False)
            message.event = event
            message.original_filename = media_file.name
            message.file_size = media_file.size
            message.duration = form.media_duration
            try:
                message.save()
            except Exception as exc:
                if not is_storage_error(exc):
                    raise
                logger.exception("Remote guestbook storage error for event=%s", event.pk)
                recover_from_storage_error()
                form.add_error("media_file", STORAGE_UNAVAILABLE_MESSAGE)
            else:
                logger.info("Remote guestbook message recorded event=%s message=%s", event.pk, message.pk)
                code.used_at = timezone.now()
                code.used_by_name = message.guest_name
                code.save(update_fields=["used_at", "used_by_name"])
                del request.session[session_key]
                request.session[sent_key] = True
                # Comme la fin de service d'un agent : on ne lance jamais un montage partiel tant
                # qu'un agent enregistre encore sur place, il le declenchera a son tour.
                if not has_open_shifts(event):
                    queue_guestbook_movie(event, trigger="remote_family")
                sent = True
    else:
        form = GuestBookMessageForm(require_name=True)

    return render(
        request,
        "guestbook/remote_capture.html",
        {
            "event": event,
            "form": form,
            "sent": sent,
            "max_duration_seconds": settings.MEMORA_GUESTBOOK_MAX_VIDEO_DURATION_SECONDS,
        },
    )
