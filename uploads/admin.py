from django.contrib import admin

from .models import GuestUpload, MomentTemplate, UploadCategory, UploadCategoryTemplate


@admin.register(MomentTemplate)
class MomentTemplateAdmin(admin.ModelAdmin):
    list_display = (
        "label",
        "code",
        "status",
        "usage_count",
        "is_active",
        "auto_promoted_at",
        "created_by",
    )
    list_editable = ("status", "is_active")
    list_filter = ("status", "is_active", "suggested_event_types", "auto_promoted_at")
    search_fields = ("label", "code", "created_by__username", "created_by__email")
    filter_horizontal = ("suggested_event_types",)
    prepopulated_fields = {"code": ("label",)}
    readonly_fields = ("usage_count", "auto_promoted_at", "created_at", "updated_at")
    actions = ("approve_moments", "reject_moments")

    @admin.action(description="Valider les moments selectionnes")
    def approve_moments(self, request, queryset):
        queryset.update(status=MomentTemplate.ModerationStatus.APPROVED, is_active=True)

    @admin.action(description="Rejeter les moments selectionnes")
    def reject_moments(self, request, queryset):
        queryset.update(status=MomentTemplate.ModerationStatus.REJECTED, is_active=False)


@admin.register(UploadCategoryTemplate)
class UploadCategoryTemplateAdmin(admin.ModelAdmin):
    list_display = ("label", "event_type", "code", "sort_order", "is_active")
    list_editable = ("sort_order", "is_active")
    list_filter = ("event_type", "is_active")
    search_fields = ("label", "code", "event_type__label")
    prepopulated_fields = {"code": ("label",)}


@admin.register(UploadCategory)
class UploadCategoryAdmin(admin.ModelAdmin):
    list_display = ("label", "event", "code", "sort_order", "is_active")
    list_editable = ("sort_order", "is_active")
    list_filter = ("event", "is_active")
    search_fields = ("label", "code", "event__title")
    prepopulated_fields = {"code": ("label",)}


@admin.register(GuestUpload)
class GuestUploadAdmin(admin.ModelAdmin):
    list_display = (
        "original_filename",
        "event",
        "category",
        "media_type",
        "moderation_status",
        "file_size",
        "uploaded_at",
        "is_selected_for_movie",
        "is_deleted",
    )
    list_filter = (
        "media_type",
        "moderation_status",
        "category",
        "is_selected_for_movie",
        "is_deleted",
        "uploaded_at",
    )
    search_fields = (
        "original_filename",
        "event__title",
        "ip_address",
        "session_key",
    )
    readonly_fields = ("uploaded_at",)
