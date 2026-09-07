from pathlib import Path

from django.conf import settings
from django.db import models


def guestbook_message_upload_path(instance, filename):
    event_slug = instance.event.slug if instance.event_id else "pending"
    return f"events/{event_slug}/livre-dor/{filename}"


class GuestBookMessage(models.Model):
    """Message video enregistre au stand livre d'or par l'agent Memora.

    Delibetement separe de GuestUpload : ces messages ne doivent jamais entrer
    dans le pipeline d'analyse IA ni la selection automatique du film — ils
    vivent dans leur propre table, pas juste derriere un indicateur qu'on
    pourrait oublier de filtrer.
    """

    event = models.ForeignKey(
        "events.Event",
        on_delete=models.CASCADE,
        related_name="guestbook_messages",
    )
    guest_name = models.CharField(
        max_length=120,
        blank=True,
        help_text="Facultatif : de la part de qui est ce message.",
    )
    media_file = models.FileField(upload_to=guestbook_message_upload_path)
    duration = models.DurationField(blank=True, null=True)
    original_filename = models.CharField(max_length=255)
    file_size = models.PositiveBigIntegerField()
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="recorded_guestbook_messages",
        help_text="Agent qui a capture ce message.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "message du livre d'or"
        verbose_name_plural = "messages du livre d'or"

    def __str__(self):
        who = self.guest_name or "Invite anonyme"
        return f"{who} - {self.event}"

    @property
    def extension(self):
        return Path(self.original_filename).suffix.lower().lstrip(".")
