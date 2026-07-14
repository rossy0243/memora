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
    actions = ("mark_events_paid",)
    list_display = (
        "title",
        "organizer",
        "event_type",
        "event_date",
        "payment_status",
        "formatted_price",
        "paid_at",
        "is_active",
        "guest_access_code",
        "media_retention_days",
        "created_at",
    )
    list_filter = ("payment_status", "event_type", "is_active", "event_date", "created_at")
    search_fields = ("title", "couple_name", "location", "organizer__username", "payment_reference")
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
            "Paiement",
            {
                "description": "Activation manuelle MVP : 1 evenement = 59 USD. Marquez l'evenement comme paye apres verification du paiement.",
                "fields": (
                    "payment_status",
                    "price_amount",
                    "price_currency",
                    "paid_at",
                    "payment_provider",
                    "payment_reference",
                ),
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

    @admin.action(description="Marquer les evenements selectionnes comme payes")
    def mark_events_paid(self, request, queryset):
        updated = 0
        for event in queryset:
            event.mark_paid(provider="manual-admin")
            event.save(update_fields=["payment_status", "paid_at", "payment_provider", "payment_reference", "updated_at"])
            updated += 1
        self.message_user(request, f"{updated} evenement(s) marque(s) comme paye(s).")
