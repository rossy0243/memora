from django.contrib import admin

from .models import GeneratedMovie


@admin.register(GeneratedMovie)
class GeneratedMovieAdmin(admin.ModelAdmin):
    list_display = ("event", "status", "generated_at", "duration", "created_at")
    list_filter = ("status", "generated_at", "created_at")
    search_fields = ("event__title", "error_logs")
    readonly_fields = ("created_at", "updated_at")
