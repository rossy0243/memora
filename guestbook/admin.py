from django.contrib import admin

from .models import GuestBookAssignment, GuestBookMessage, GuestBookMovie


@admin.register(GuestBookAssignment)
class GuestBookAssignmentAdmin(admin.ModelAdmin):
    """Vue transversale des missions, tous evenements confondus.

    L'affectation elle-meme se fait plutot depuis la fiche evenement (inline) :
    cette page sert a retrouver rapidement ou travaille un agent donne."""

    list_display = ("event", "agent", "started_at", "ended_at", "assigned_at")
    list_filter = ("agent",)
    search_fields = ("event__title", "agent__username")
    list_select_related = ("event", "agent")
    autocomplete_fields = ("agent",)


@admin.register(GuestBookMessage)
class GuestBookMessageAdmin(admin.ModelAdmin):
    list_display = ("event", "guest_name", "recorded_by", "duration", "created_at")
    list_filter = ("event",)
    search_fields = ("guest_name", "event__title", "recorded_by__username")
    readonly_fields = (
        "event",
        "guest_name",
        "media_file",
        "duration",
        "original_filename",
        "file_size",
        "recorded_by",
        "created_at",
    )

    def has_add_permission(self, request):
        # Un message nait du stand livre d'or, jamais de l'admin.
        return False


@admin.register(GuestBookMovie)
class GuestBookMovieAdmin(admin.ModelAdmin):
    list_display = (
        "event",
        "status",
        "message_count",
        "trigger",
        "requested_at",
        "completed_at",
    )
    list_filter = ("status", "trigger")
    search_fields = ("event__title",)
    list_select_related = ("event",)
    readonly_fields = (
        "event",
        "final_file",
        "duration",
        "message_count",
        "render_provider",
        "error_message",
        "trigger",
        "requested_at",
        "started_at",
        "completed_at",
        "updated_at",
    )
    actions = ("requeue_montage",)

    def has_add_permission(self, request):
        return False

    @admin.action(description="Relancer le montage (remet en file d'attente)")
    def requeue_montage(self, request, queryset):
        updated = queryset.update(status=GuestBookMovie.Status.PENDING, error_message="")
        self.message_user(request, f"{updated} montage(s) remis en file d'attente.")
