from django.conf import settings
from django.contrib import admin, messages
from django.utils import timezone

from .models import GeneratedMovie, MediaAnalysis, MusicTrack
from .services import get_movie_candidate_uploads, queue_only_deliverable_regeneration
from .soundtrack import choose_movie_soundtrack


@admin.register(MusicTrack)
class MusicTrackAdmin(admin.ModelAdmin):
    actions = ("measure_tempo",)
    list_display = ("title", "mood", "bpm", "first_beat_offset", "is_active", "is_guestbook_default", "attribution")
    list_filter = ("mood", "is_active", "is_guestbook_default")
    list_editable = ("is_active",)
    search_fields = ("title", "attribution", "source")
    readonly_fields = ("bpm", "first_beat_offset", "created_at", "updated_at")
    fields = (
        "title",
        "audio_file",
        "mood",
        "is_active",
        "is_guestbook_default",
        "attribution",
        "source",
        "bpm",
        "first_beat_offset",
        "created_at",
        "updated_at",
    )

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        # Mesure automatique du tempo a l'upload (ou si le fichier a change).
        if "audio_file" in form.changed_data or obj.bpm is None:
            if obj.measure_and_store_tempo():
                self.message_user(request, f"Tempo mesure : {obj.bpm} BPM.")
            else:
                self.message_user(
                    request,
                    "Tempo non mesure (ffmpeg indisponible ?). Le calage rythmique "
                    "sera ignore pour cette piste ; utilisez l'action « Mesurer le tempo ».",
                    level=messages.WARNING,
                )

    @admin.action(description="Mesurer le tempo")
    def measure_tempo(self, request, queryset):
        measured = 0
        for track in queryset:
            if track.measure_and_store_tempo():
                measured += 1
        self.message_user(request, f"{measured} piste(s) mesuree(s).")


@admin.register(GeneratedMovie)
class GeneratedMovieAdmin(admin.ModelAdmin):
    actions = (
        "regenerate_movies",
        "cancel_renders",
        "regenerate_only_hero",
        "regenerate_only_full",
        "regenerate_only_teaser",
    )
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
    readonly_fields = (
        "created_at",
        "updated_at",
        "organizer_notified_at",
        "processing_started_at",
        "elapsed_display",
        "candidates_display",
        "soundtrack_display",
    )

    @admin.display(description="Temps ecoule (rendu en cours)")
    def elapsed_display(self, obj):
        if obj.status != GeneratedMovie.Status.PROCESSING or not obj.processing_started_at:
            return "—"
        elapsed = timezone.now() - obj.processing_started_at
        minutes, seconds = divmod(int(elapsed.total_seconds()), 60)
        hours, minutes = divmod(minutes, 60)
        return f"{hours}h{minutes:02d}m{seconds:02d}s"

    @admin.display(description="Candidats par livrable")
    def candidates_display(self, obj):
        variants = (
            ("hero", settings.MEMORA_MOVIE_HERO_DURATION_SECONDS, settings.MEMORA_MOVIE_MAX_PER_GUEST.get("hero")),
            ("full", settings.MEMORA_MOVIE_FULL_DURATION_SECONDS, settings.MEMORA_MOVIE_MAX_PER_GUEST.get("full")),
            ("teaser", settings.MEMORA_MOVIE_TEASER_DURATION_SECONDS, settings.MEMORA_MOVIE_MAX_PER_GUEST.get("teaser")),
        )
        parts = []
        for deliverable, max_duration, max_per_guest in variants:
            count = len(
                list(
                    get_movie_candidate_uploads(
                        obj.event, max_duration=max_duration, max_per_guest=max_per_guest, deliverable=deliverable
                    )
                )
            )
            parts.append(f"{deliverable}: {count}")
        return " · ".join(parts)

    @admin.display(description="Piste musicale retenue")
    def soundtrack_display(self, obj):
        soundtrack = choose_movie_soundtrack(obj.event, [])
        return f"{soundtrack.track_name or '(aucune)'} — {soundtrack.reason}"

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
            # Regeneration volontaire : repart de zero sur les trois livrables,
            # sinon le pipeline sauterait un livrable deja present en le
            # prenant pour un reste d'une tentative interrompue (voir
            # processing.management.commands.regenerate_event_movie).
            movie.final_file = None
            movie.full_file = None
            movie.teaser_file = None
            movie.teaser_light_file = None
            movie.full_light_file = None
            movie.full_duration = None
            movie.teaser_duration = None
            movie.save(
                update_fields=[
                    "status",
                    "error_logs",
                    "progress_percent",
                    "progress_message",
                    "final_file",
                    "full_file",
                    "teaser_file",
                    "teaser_light_file",
                    "full_light_file",
                    "full_duration",
                    "teaser_duration",
                    "updated_at",
                ]
            )
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

    @admin.action(description="Arreter le rendu en cours")
    def cancel_renders(self, request, queryset):
        cancelled = 0
        skipped = 0
        for movie in queryset:
            if movie.status != GeneratedMovie.Status.PROCESSING:
                skipped += 1
                continue
            movie.cancel_requested = True
            movie.save(update_fields=["cancel_requested", "updated_at"])
            cancelled += 1

        if cancelled:
            self.message_user(request, f"Arret demande pour {cancelled} film(s).")
        if skipped:
            self.message_user(
                request,
                f"{skipped} film(s) ignore(s) car aucun rendu n'est en cours.",
                level=messages.WARNING,
            )

    def _regenerate_only(self, request, queryset, deliverable):
        regenerated = 0
        skipped = 0
        for movie in queryset:
            try:
                queue_only_deliverable_regeneration(movie, deliverable)
                regenerated += 1
            except ValueError as exc:
                skipped += 1
                self.message_user(request, f"{movie} : {exc}", level=messages.WARNING)

        if regenerated:
            self.message_user(
                request,
                f"{regenerated} film(s) : {deliverable} remis en attente, les autres livrables "
                "ne sont pas touches (traite au prochain passage du cron).",
            )
        return regenerated, skipped

    @admin.action(description="Regenerer uniquement le heros")
    def regenerate_only_hero(self, request, queryset):
        self._regenerate_only(request, queryset, "hero")

    @admin.action(description="Regenerer uniquement l'integrale")
    def regenerate_only_full(self, request, queryset):
        self._regenerate_only(request, queryset, "full")

    @admin.action(description="Regenerer uniquement le teaser")
    def regenerate_only_teaser(self, request, queryset):
        self._regenerate_only(request, queryset, "teaser")


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
