from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from core.storage_errors import STORAGE_UNAVAILABLE_MESSAGE, is_storage_error, recover_from_storage_error
from processing.services import build_event_zip, create_event_movie_job, get_event_movie_schedule_at
from uploads.models import GuestUpload, UploadCategory

from .forms import EventForm
from .access import grant_guest_access, has_guest_access
from .models import Event
from .services import build_event_qr_code_png


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
        try:
            return super().form_valid(form)
        except Exception as exc:
            if not is_storage_error(exc):
                raise
            recover_from_storage_error()
            form.add_error("cover_image", STORAGE_UNAVAILABLE_MESSAGE)
            return self.form_invalid(form)

    def get_success_url(self):
        return reverse_lazy("events:detail", kwargs={"pk": self.object.pk})


class EventUpdateView(OrganizerEventMixin, UpdateView):
    form_class = EventForm
    template_name = "events/event_form.html"

    def form_valid(self, form):
        try:
            return super().form_valid(form)
        except Exception as exc:
            if not is_storage_error(exc):
                raise
            recover_from_storage_error()
            form.add_error("cover_image", STORAGE_UNAVAILABLE_MESSAGE)
            return self.form_invalid(form)

    def get_success_url(self):
        return reverse_lazy("events:detail", kwargs={"pk": self.object.pk})


class EventDetailView(OrganizerEventMixin, DetailView):
    template_name = "events/event_detail.html"
    context_object_name = "event"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        uploads = (
            self.object.guest_uploads.filter(is_deleted=False)
            .exclude(moderation_status=GuestUpload.ModerationStatus.REJECTED)
            .select_related("category")
            .order_by("-uploaded_at")
        )
        stats = uploads.aggregate(
            total=Count("id"),
            photos=Count("id", filter=Q(media_type=GuestUpload.MediaType.IMAGE)),
            videos=Count("id", filter=Q(media_type=GuestUpload.MediaType.VIDEO)),
            approved=Count("id", filter=Q(moderation_status=GuestUpload.ModerationStatus.APPROVED)),
            selected_for_movie=Count(
                "id",
                filter=Q(
                    is_selected_for_movie=True,
                    moderation_status=GuestUpload.ModerationStatus.APPROVED,
                ),
            ),
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
                "public_event_url": self.request.build_absolute_uri(self.object.get_public_url()),
                "event_qr_code_url": reverse("events:qr_code", kwargs={"pk": self.object.pk}),
                **get_movie_panel_context(self.object),
            }
        )
        return context


class EventMediaListView(OrganizerEventMixin, ListView):
    template_name = "events/event_media_list.html"
    context_object_name = "uploads"
    paginate_by = 24

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        self.event = get_object_or_404(Event, pk=kwargs["pk"], organizer=request.user)
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        queryset = (
            GuestUpload.objects.filter(event=self.event, is_deleted=False)
            .select_related("category")
            .order_by("-uploaded_at")
        )
        self.selected_category = self.request.GET.get("category", "")
        self.selected_media_type = self.request.GET.get("type", "")
        self.selected_movie_filter = self.request.GET.get("movie", "")
        self.selected_moderation_status = self.request.GET.get("status", "")

        if self.selected_category:
            queryset = queryset.filter(category__code=self.selected_category)
        if self.selected_media_type in {GuestUpload.MediaType.IMAGE, GuestUpload.MediaType.VIDEO}:
            queryset = queryset.filter(media_type=self.selected_media_type)
        if self.selected_movie_filter == "selected":
            queryset = queryset.filter(
                is_selected_for_movie=True,
                moderation_status=GuestUpload.ModerationStatus.APPROVED,
            )
        if self.selected_moderation_status in GuestUpload.ModerationStatus.values:
            queryset = queryset.filter(moderation_status=self.selected_moderation_status)
        elif self.selected_moderation_status != GuestUpload.ModerationStatus.REJECTED:
            queryset = queryset.exclude(moderation_status=GuestUpload.ModerationStatus.REJECTED)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "event": self.event,
                "categories": UploadCategory.objects.filter(event=self.event, is_active=True),
                "media_types": GuestUpload.MediaType,
                "moderation_statuses": GuestUpload.ModerationStatus,
                "selected_category": self.selected_category,
                "selected_media_type": self.selected_media_type,
                "selected_movie_filter": self.selected_movie_filter,
                "selected_moderation_status": self.selected_moderation_status,
                "selected_for_movie_count": self.event.guest_uploads.filter(
                    is_deleted=False,
                    moderation_status=GuestUpload.ModerationStatus.APPROVED,
                    is_selected_for_movie=True,
                ).count(),
            }
        )
        return context


def public_event_preview(request, slug, access_key):
    event = get_object_or_404(
        Event,
        slug=slug,
        public_access_key=access_key,
        is_active=True,
    )
    if event.requires_guest_access_code and not has_guest_access(request, event):
        access_error = ""
        if request.method == "POST":
            if event.check_guest_access_code(request.POST.get("guest_access_code")):
                grant_guest_access(request, event)
                return redirect(event.get_public_url())
            access_error = "Code incorrect."
        return render(
            request,
            "events/public_event_access.html",
            {"event": event, "access_error": access_error},
        )
    return render(request, "events/public_event.html", {"event": event})


@login_required
@require_POST
def toggle_movie_selection(request, pk, upload_pk):
    event = get_object_or_404(Event, pk=pk, organizer=request.user)
    upload = get_object_or_404(
        GuestUpload,
        pk=upload_pk,
        event=event,
        is_deleted=False,
        moderation_status=GuestUpload.ModerationStatus.APPROVED,
    )
    upload.is_selected_for_movie = not upload.is_selected_for_movie
    upload.save(update_fields=["is_selected_for_movie"])

    next_url = request.POST.get("next") or reverse("events:media_list", kwargs={"pk": event.pk})
    return redirect(next_url)


@login_required
@require_POST
def set_media_moderation_status(request, pk, upload_pk):
    event = get_object_or_404(Event, pk=pk, organizer=request.user)
    upload = get_object_or_404(
        GuestUpload,
        pk=upload_pk,
        event=event,
        is_deleted=False,
    )
    status = request.POST.get("status", "")
    if status in {GuestUpload.ModerationStatus.APPROVED, GuestUpload.ModerationStatus.REJECTED}:
        upload.moderation_status = status
        if status != GuestUpload.ModerationStatus.APPROVED:
            upload.is_selected_for_movie = False
        upload.save(update_fields=["moderation_status", "is_selected_for_movie"])

    next_url = request.POST.get("next") or reverse("events:media_list", kwargs={"pk": event.pk})
    return redirect(next_url)


@login_required
@require_POST
def generate_movie(request, pk):
    event = get_object_or_404(Event, pk=pk, organizer=request.user)
    create_event_movie_job(event)
    return redirect(reverse("events:detail", kwargs={"pk": event.pk}))


@login_required
def movie_status_panel(request, pk):
    event = get_object_or_404(Event, pk=pk, organizer=request.user)
    return render(request, "events/partials/movie_panel.html", get_movie_panel_context(event))


def get_movie_panel_context(event):
    latest_movie = event.generated_movies.order_by("-created_at").first()
    return {
        "event": event,
        "latest_movie": latest_movie,
        "movie_schedule_at": get_event_movie_schedule_at(event),
        "movie_status_url": reverse("events:movie_status", kwargs={"pk": event.pk}),
        "movie_is_live": bool(
            latest_movie
            and latest_movie.status in {"pending", "processing"}
        ),
    }


@login_required
def event_qr_code(request, pk):
    event = get_object_or_404(Event, pk=pk, organizer=request.user)
    public_url = request.build_absolute_uri(event.get_public_url())
    response = HttpResponse(build_event_qr_code_png(public_url), content_type="image/png")
    response["Content-Disposition"] = f'inline; filename="{event.slug}-qr.png"'
    response["Cache-Control"] = "private, max-age=300"
    return response


@login_required
def download_event_zip(request, pk):
    event = get_object_or_404(Event, pk=pk, organizer=request.user)
    filename, content = build_event_zip(event)
    response = HttpResponse(content, content_type="application/zip")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
