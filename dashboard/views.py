from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from events.models import Event


@login_required
def dashboard_home(request):
    events = Event.objects.filter(organizer=request.user)
    return render(request, "dashboard/home.html", {"events": events})
