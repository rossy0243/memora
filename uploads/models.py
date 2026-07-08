from pathlib import Path

from django.db import models


def guest_media_upload_path(instance, filename):
    event_slug = instance.event.slug if instance.event_id else "pending"
    category_code = instance.category.code if instance.category_id else "uncategorized"
    return f"events/{event_slug}/uploads/{category_code}/{filename}"


class UploadCategory(models.Model):
    event = models.ForeignKey(
        "events.Event",
        on_delete=models.CASCADE,
        related_name="upload_categories",
    )
    code = models.SlugField(max_length=40)
    label = models.CharField(max_length=80)
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["event_id", "sort_order", "label"]
        constraints = [
            models.UniqueConstraint(fields=["event", "code"], name="unique_upload_category_per_event"),
        ]
        verbose_name = "categorie d'upload"
        verbose_name_plural = "categories d'upload"

    def __str__(self):
        return f"{self.label} - {self.event}"


class GuestUpload(models.Model):
    class MediaType(models.TextChoices):
        IMAGE = "image", "Image"
        VIDEO = "video", "Video"

    event = models.ForeignKey(
        "events.Event",
        on_delete=models.CASCADE,
        related_name="guest_uploads",
    )
    category = models.ForeignKey(
        UploadCategory,
        on_delete=models.PROTECT,
        related_name="guest_uploads",
    )
    media_file = models.FileField(upload_to=guest_media_upload_path)
    media_type = models.CharField(max_length=12, choices=MediaType.choices)
    original_filename = models.CharField(max_length=255)
    file_size = models.PositiveBigIntegerField()
    duration = models.DurationField(blank=True, null=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    user_agent = models.TextField(blank=True)
    session_key = models.CharField(max_length=80, blank=True)
    is_selected_for_movie = models.BooleanField(default=False)
    is_deleted = models.BooleanField(default=False)

    class Meta:
        ordering = ["-uploaded_at"]
        indexes = [
            models.Index(fields=["event", "uploaded_at"]),
            models.Index(fields=["event", "media_type"]),
            models.Index(fields=["event", "is_deleted"]),
            models.Index(fields=["ip_address", "uploaded_at"]),
            models.Index(fields=["session_key", "uploaded_at"]),
        ]

    def __str__(self):
        return f"{self.event} - {self.original_filename}"

    @property
    def extension(self):
        return Path(self.original_filename).suffix.lower().lstrip(".")
