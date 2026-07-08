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
    generated_at = models.DateTimeField(blank=True, null=True)
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
