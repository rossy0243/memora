from django.contrib import admin

from uploads.models import UploadCategory

from .models import Event, EventType


@admin.register(EventType)
class EventTypeAdmin(admin.ModelAdmin):
    list_display = ("label", "code", "sort_order", "is_active")
    list_editable = ("sort_order", "is_active")
    list_filter = ("is_active",)
    search_fields = ("label", "code")
    prepopulated_fields = {"code": ("label",)}


class UploadCategoryInline(admin.TabularInline):
    model = UploadCategory
    extra = 0
    fields = ("label", "code", "sort_order", "is_active")
    prepopulated_fields = {"code": ("label",)}


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    inlines = [UploadCategoryInline]
    list_display = (
        "title",
        "organizer",
        "event_type",
        "event_date",
        "is_active",
        "guest_access_code",
        "media_retention_days",
        "created_at",
    )
    list_filter = ("event_type", "is_active", "event_date", "created_at")
    search_fields = ("title", "couple_name", "location", "organizer__username")
    prepopulated_fields = {"slug": ("title",)}
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (
            "Informations",
            {
                "fields": (
                    "organizer",
                    "title",
                    "slug",
                    "couple_name",
                    "event_type",
                    "event_date",
                    "location",
                )
            },
        ),
        (
            "Experience invite",
            {
                "fields": (
                    "cover_image",
                    "welcome_message",
                    "guest_access_code",
                    "qr_code_image",
                    "is_active",
                )
            },
        ),
        (
            "Retention",
            {
                "fields": ("media_retention_days",),
            },
        ),
        (
            "Dates",
            {
                "fields": ("created_at", "updated_at"),
            },
        ),
    )
