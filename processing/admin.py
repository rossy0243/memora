from django.contrib import admin, messages

from .models import GeneratedMovie, MediaAnalysis


@admin.register(GeneratedMovie)
class GeneratedMovieAdmin(admin.ModelAdmin):
    actions = ("regenerate_movies",)
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

    @admin.action(description="Regenerer le film souvenir (remet en attente pour le worker)")
    def regenerate_movies(self, request, queryset):
        regenerated = 0
        skipped = 0
        for movie in queryset:
            if movie.status == GeneratedMovie.Status.PROCESSING:
                skipped += 1
                continue
            movie.status = GeneratedMovie.Status.PENDING
            movie.error_logs = ""
            movie.progress_percent = 0
            movie.progress_message = ""
            movie.save(update_fields=["status", "error_logs", "progress_percent", "progress_message", "updated_at"])
            regenerated += 1

        if regenerated:
            self.message_user(
                request,
                f"{regenerated} film(s) remis en attente. Lancez `process_pending_movies` "
                "(ou `process_event_movie <id> --include-processing`) pour les regenerer.",
            )
        if skipped:
            self.message_user(
                request,
                f"{skipped} film(s) ignore(s) car deja en cours de traitement.",
                level=messages.WARNING,
            )


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
