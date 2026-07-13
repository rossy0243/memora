from django.contrib import admin

from .models import GeneratedMovie, MediaAnalysis


@admin.register(GeneratedMovie)
class GeneratedMovieAdmin(admin.ModelAdmin):
    list_display = (
        "event",
        "status",
        "render_provider",
        "music_mood",
        "generated_at",
        "organizer_notified_at",
        "duration",
        "created_at",
    )
    list_filter = ("status", "render_provider", "music_mood", "generated_at", "organizer_notified_at", "created_at")
    search_fields = ("event__title", "music_track", "error_logs")
    readonly_fields = ("created_at", "updated_at", "organizer_notified_at")


@admin.register(MediaAnalysis)
class MediaAnalysisAdmin(admin.ModelAdmin):
    list_display = (
        "upload",
        "status",
        "provider",
        "movie_score",
        "technical_score",
        "emotion_score",
        "energy_score",
        "analyzed_at",
    )
    list_filter = ("status", "provider", "analyzed_at", "created_at")
    search_fields = ("upload__event__title", "upload__original_filename", "summary", "error_logs")
    readonly_fields = ("created_at", "updated_at", "analyzed_at")
