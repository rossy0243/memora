from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse_lazy
from django.views.generic import CreateView, DetailView, UpdateView

from processing.services import build_event_zip
from uploads.models import GuestUpload, UploadCategory

from .forms import EventForm
from .models import Event
from .services import generate_event_qr_code


class OrganizerEventMixin(LoginRequiredMixin):
    model = Event

    def get_queryset(self):
        return Event.objects.filter(organizer=self.request.user)


class EventCreateView(LoginRequiredMixin, CreateView):
    model = Event
    form_class = EventForm
    template_name = "events/event_form.html"

    def form_valid(self, form):
        form.instance.organizer = self.request.user
        response = super().form_valid(form)
        generate_event_qr_code(
            self.object,
            self.request.build_absolute_uri(self.object.get_public_url()),
        )
        return response

    def get_success_url(self):
        return reverse_lazy("events:detail", kwargs={"pk": self.object.pk})


class EventUpdateView(OrganizerEventMixin, UpdateView):
    form_class = EventForm
    template_name = "events/event_form.html"

    def form_valid(self, form):
        response = super().form_valid(form)
        generate_event_qr_code(
            self.object,
            self.request.build_absolute_uri(self.object.get_public_url()),
        )
        return response

    def get_success_url(self):
        return reverse_lazy("events:detail", kwargs={"pk": self.object.pk})


class EventDetailView(OrganizerEventMixin, DetailView):
    template_name = "events/event_detail.html"
    context_object_name = "event"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        uploads = (
            self.object.guest_uploads.filter(is_deleted=False)
            .select_related("category")
            .order_by("-uploaded_at")
        )
        stats = uploads.aggregate(
            total=Count("id"),
            photos=Count("id", filter=Q(media_type=GuestUpload.MediaType.IMAGE)),
            videos=Count("id", filter=Q(media_type=GuestUpload.MediaType.VIDEO)),
        )

        counts_by_category = {
            item["category_id"]: item["total"]
            for item in uploads.values("category_id").annotate(total=Count("id"))
        }
        category_stats = []
        for category in UploadCategory.objects.filter(event=self.object, is_active=True):
            category_stats.append(
                {
                    "category": category,
                    "count": counts_by_category.get(category.id, 0),
                }
            )

        context.update(
            {
                "media_stats": stats,
                "category_stats": category_stats,
                "latest_uploads": uploads[:8],
            }
        )
        return context


def public_event_preview(request, slug):
    event = get_object_or_404(Event, slug=slug, is_active=True)
    return render(request, "events/public_event.html", {"event": event})


@login_required
def download_event_zip(request, pk):
    event = get_object_or_404(Event, pk=pk, organizer=request.user)
    filename, content = build_event_zip(event)
    response = HttpResponse(content, content_type="application/zip")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
