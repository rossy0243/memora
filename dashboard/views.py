from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone

from accounts.models import OrganizerProfile
from accounts.services import commission_summary_for_user, tier_progress_for_profile
from core.models import format_price_amount
from events.models import Event
from processing.models import GeneratedMovie


@login_required
def dashboard_home(request):
    events = list(Event.objects.filter(organizer=request.user).order_by("-event_date", "-created_at"))
    today = timezone.localdate()
    for event in events:
        event.latest_movie = event.generated_movies.order_by("-created_at").first()
        event.post_event_status = _event_post_status(event, today)

    profile = OrganizerProfile.for_user(request.user)
    summary = commission_summary_for_user(request.user)
    progress = tier_progress_for_profile(profile)
    earnings_panel = {
        "tier": progress["tier"],
        "tier_label": progress["tier_label"],
        "current_rate": progress["current_rate"],
        "next_tier_label": progress["next_tier_label"],
        "events_to_next_tier": progress["events_to_next_tier"],
        "paid_count": progress["paid_count"],
        "referral_code": profile.referral_code,
        "referral_url": request.build_absolute_uri(
            f"/comptes/inscription/?parrain={profile.referral_code}"
        ),
        "pending": format_price_amount(summary["pending_amount"], summary["currency"]),
        "paid": format_price_amount(summary["paid_amount"], summary["currency"]),
        "total": format_price_amount(summary["total_amount"], summary["currency"]),
        "entries": summary["entries"][:5],
        "referred_count": OrganizerProfile.objects.filter(referred_by=request.user).count(),
    }

    return render(
        request,
        "dashboard/home.html",
        {"events": events, "today": today, "earnings_panel": earnings_panel},
    )


def _event_post_status(event, today):
    latest_movie = event.latest_movie
    if latest_movie and latest_movie.status == GeneratedMovie.Status.COMPLETED and latest_movie.final_file:
        return {"label": "Film prêt", "class": "status-pill--active"}
    if latest_movie and latest_movie.status == GeneratedMovie.Status.PROCESSING:
        return {"label": "Film en cours", "class": ""}
    if latest_movie and latest_movie.status == GeneratedMovie.Status.PENDING:
        return {"label": "Film programmé", "class": ""}
    if latest_movie and latest_movie.status == GeneratedMovie.Status.FAILED:
        return {"label": "À relancer", "class": "status-pill--danger"}
    if event.event_date > today:
        return {"label": "Avant événement", "class": ""}
    if event.event_date == today:
        return {"label": "Jour J", "class": "status-pill--active"}
    return {"label": "Film prévu", "class": ""}
