from django.db import models


def generated_movie_upload_path(instance, filename):
    event_slug = instance.event.slug if instance.event_id else "pending"
    return f"events/{event_slug}/movies/{filename}"


class GeneratedMovie(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "En attente"
        PROCESSING = "processing", "En cours"
        COMPLETED = "completed", "Termine"
        FAILED = "failed", "Echec"

    event = models.ForeignKey(
        "events.Event",
        on_delete=models.CASCADE,
        related_name="generated_movies",
    )
    status = models.CharField(
        max_length=24,
        choices=Status.choices,
        default=Status.PENDING,
    )
    final_file = models.FileField(
        upload_to=generated_movie_upload_path,
        blank=True,
        null=True,
    )
    render_provider = models.CharField(max_length=40, default="ffmpeg")
    music_mood = models.CharField(max_length=80, blank=True)
    music_track = models.CharField(max_length=255, blank=True)
    edit_decision_data = models.JSONField(default=dict, blank=True)
    progress_percent = models.PositiveSmallIntegerField(default=0)
    progress_message = models.CharField(max_length=160, blank=True)
    generated_at = models.DateTimeField(blank=True, null=True)
    organizer_notified_at = models.DateTimeField(blank=True, null=True)
    duration = models.DurationField(blank=True, null=True)
    error_logs = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["event", "status"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return f"Film souvenir - {self.event} ({self.get_status_display()})"


class MediaAnalysis(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "En attente"
        PROCESSING = "processing", "En cours"
        COMPLETED = "completed", "Termine"
        FAILED = "failed", "Echec"

    upload = models.OneToOneField(
        "uploads.GuestUpload",
        on_delete=models.CASCADE,
        related_name="analysis",
    )
    status = models.CharField(
        max_length=24,
        choices=Status.choices,
        default=Status.PENDING,
    )
    provider = models.CharField(max_length=80, default="local_heuristic_v1")
    technical_score = models.FloatField(default=0)
    emotion_score = models.FloatField(default=0)
    energy_score = models.FloatField(default=0)
    movie_score = models.FloatField(default=0)
    brightness = models.FloatField(blank=True, null=True)
    sharpness = models.FloatField(blank=True, null=True)
    tags = models.JSONField(default=list, blank=True)
    provider_payload = models.JSONField(default=dict, blank=True)
    summary = models.CharField(max_length=255, blank=True)
    analyzed_at = models.DateTimeField(blank=True, null=True)
    error_logs = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-movie_score", "-created_at"]
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["movie_score"]),
        ]
        verbose_name = "analyse media"
        verbose_name_plural = "analyses medias"

    def __str__(self):
        return f"Analyse - {self.upload} ({self.get_status_display()})"
