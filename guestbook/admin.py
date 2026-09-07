from django.contrib import admin

from .models import GuestBookMessage


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
