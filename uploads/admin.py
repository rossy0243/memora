from django.contrib import admin

from .models import GuestUpload, UploadCategory


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
        "file_size",
        "uploaded_at",
        "is_selected_for_movie",
        "is_deleted",
    )
    list_filter = (
        "media_type",
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
