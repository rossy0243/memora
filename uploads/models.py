from pathlib import Path

from django.conf import settings
from django.db import models


def guest_media_upload_path(instance, filename):
    event_slug = instance.event.slug if instance.event_id else "pending"
    category_code = instance.category.code if instance.category_id else "uncategorized"
    return f"events/{event_slug}/uploads/{category_code}/{filename}"


class UploadCategoryTemplate(models.Model):
    event_type = models.ForeignKey(
        "events.EventType",
        on_delete=models.CASCADE,
        related_name="upload_category_templates",
    )
    code = models.SlugField(max_length=40)
    label = models.CharField(max_length=80)
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["event_type_id", "sort_order", "label"]
        constraints = [
            models.UniqueConstraint(
                fields=["event_type", "code"],
                name="unique_upload_category_template_per_event_type",
            ),
        ]
        verbose_name = "modele de moment"
        verbose_name_plural = "modeles de moments"

    def __str__(self):
        return f"{self.label} - {self.event_type}"


class MomentTemplate(models.Model):
    class ModerationStatus(models.TextChoices):
        PENDING = "pending", "A valider"
        APPROVED = "approved", "Valide"
        REJECTED = "rejected", "Rejete"

    code = models.SlugField(max_length=40, unique=True)
    label = models.CharField(max_length=80)
    status = models.CharField(
        max_length=16,
        choices=ModerationStatus.choices,
        default=ModerationStatus.PENDING,
    )
    is_active = models.BooleanField(default=True)
    usage_count = models.PositiveIntegerField(default=0)
    auto_promoted_at = models.DateTimeField(blank=True, null=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="created_moment_templates",
        blank=True,
        null=True,
    )
    suggested_event_types = models.ManyToManyField(
        "events.EventType",
        related_name="moment_templates",
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["label"]
        verbose_name = "moment global"
        verbose_name_plural = "moments globaux"

    def __str__(self):
        return self.label


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

    class ModerationStatus(models.TextChoices):
        PENDING = "pending", "A verifier"
        APPROVED = "approved", "Accepte"
        REJECTED = "rejected", "Rejete"

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
    moderation_status = models.CharField(
        max_length=16,
        choices=ModerationStatus.choices,
        default=ModerationStatus.APPROVED,
    )
    is_selected_for_movie = models.BooleanField(default=False)
    is_deleted = models.BooleanField(default=False)

    class Meta:
        ordering = ["-uploaded_at"]
        indexes = [
            models.Index(fields=["event", "uploaded_at"]),
            models.Index(fields=["event", "media_type"]),
            models.Index(fields=["event", "is_deleted"]),
            models.Index(fields=["event", "moderation_status"]),
            models.Index(fields=["ip_address", "uploaded_at"]),
            models.Index(fields=["session_key", "uploaded_at"]),
        ]

    def __str__(self):
        return f"{self.event} - {self.original_filename}"

    @property
    def extension(self):
        return Path(self.original_filename).suffix.lower().lstrip(".")

    @property
    def is_approved(self):
        return self.moderation_status == self.ModerationStatus.APPROVED
