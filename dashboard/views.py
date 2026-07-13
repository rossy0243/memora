from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone

from events.models import Event
from processing.models import GeneratedMovie


@login_required
def dashboard_home(request):
    events = list(Event.objects.filter(organizer=request.user).order_by("-event_date", "-created_at"))
    today = timezone.localdate()
    for event in events:
        event.latest_movie = event.generated_movies.order_by("-created_at").first()
        event.post_event_status = _event_post_status(event, today)
    return render(request, "dashboard/home.html", {"events": events, "today": today})


def _event_post_status(event, today):
    latest_movie = event.latest_movie
    if latest_movie and latest_movie.status == GeneratedMovie.Status.COMPLETED and latest_movie.final_file:
        return {"label": "Film pret", "class": "status-pill--active"}
    if latest_movie and latest_movie.status == GeneratedMovie.Status.PROCESSING:
        return {"label": "Film en cours", "class": ""}
    if latest_movie and latest_movie.status == GeneratedMovie.Status.PENDING:
        return {"label": "Film programme", "class": ""}
    if latest_movie and latest_movie.status == GeneratedMovie.Status.FAILED:
        return {"label": "A relancer", "class": "status-pill--danger"}
    if event.event_date > today:
        return {"label": "Avant evenement", "class": ""}
    if event.event_date == today:
        return {"label": "Jour J", "class": "status-pill--active"}
    return {"label": "Film prevu", "class": ""}
