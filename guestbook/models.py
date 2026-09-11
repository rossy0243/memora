from pathlib import Path

from django.conf import settings
from django.db import models


def guestbook_message_upload_path(instance, filename):
    event_slug = instance.event.slug if instance.event_id else "pending"
    return f"events/{event_slug}/livre-dor/{filename}"


def guestbook_movie_upload_path(instance, filename):
    event_slug = instance.event.slug if instance.event_id else "pending"
    return f"events/{event_slug}/livre-dor/montage/{filename}"


class GuestBookAssignment(models.Model):
    """Mission d'un agent Memora sur le livre d'or d'un evenement.

    Plusieurs agents peuvent travailler simultanement sur le meme evenement,
    chacun avec son propre compte et son propre service (debut/fin) : un agent
    qui termine ne ferme pas le stand pour les autres. L'affectation se fait
    en interne, via l'admin.
    """

    event = models.ForeignKey(
        "events.Event",
        on_delete=models.CASCADE,
        related_name="guestbook_assignments",
    )
    agent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="guestbook_assignments",
        limit_choices_to={"agent_profile__isnull": False},
        help_text="Agent Memora affecte au livre d'or video de cet evenement.",
    )
    started_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="Debut du service de cet agent, horodate automatiquement au premier demarrage.",
    )
    ended_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="Fin du service de cet agent. Videz ce champ pour le rouvrir.",
    )
    assigned_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-assigned_at"]
        constraints = [
            models.UniqueConstraint(fields=["event", "agent"], name="unique_guestbook_assignment"),
        ]
        verbose_name = "mission agent livre d'or"
        verbose_name_plural = "missions agent livre d'or"

    def __str__(self):
        return f"{self.agent} - {self.event}"

    @property
    def is_open(self):
        """Vrai tant que cet agent est en mission : demarree, pas encore cloturee."""
        return bool(self.started_at and not self.ended_at)


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
    # True une fois le fichier R2 purge (retention evenement + grace expiree).
    # La ligne reste comme pierre tombale ; le montage du livre d'or, lui, est
    # un livrable distinct et n'est pas purge ici.
    media_purged = models.BooleanField(default=False)

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


class GuestBookMovie(models.Model):
    """Montage integral du livre d'or : tous les messages, dans l'ordre, chacun
    precede d'un carton « De la part de … ».

    Livrable distinct du film souvenir (GeneratedMovie) et rendu avec la meme
    exigence (Remotion) : un evenement a au plus un montage, regenere sur place
    si de nouveaux messages arrivent.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "En attente"
        PROCESSING = "processing", "En cours"
        COMPLETED = "completed", "Terminé"
        FAILED = "failed", "Échec"

    event = models.OneToOneField(
        "events.Event",
        on_delete=models.CASCADE,
        related_name="guestbook_movie",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    final_file = models.FileField(
        upload_to=guestbook_movie_upload_path,
        blank=True,
        null=True,
    )
    duration = models.DurationField(blank=True, null=True)
    message_count = models.PositiveIntegerField(default=0)
    render_provider = models.CharField(max_length=40, default="remotion")
    # True une fois le fichier final purge de R2 (retention livrable expiree).
    media_purged = models.BooleanField(default=False)
    error_message = models.TextField(blank=True)
    # Comment la generation a ete declenchee : fin de service de l'agent,
    # rattrapage automatique (service oublie), ou demande de l'organisateur.
    trigger = models.CharField(max_length=20, blank=True)
    requested_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(blank=True, null=True)
    completed_at = models.DateTimeField(blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        verbose_name = "montage du livre d'or"
        verbose_name_plural = "montages du livre d'or"

    def __str__(self):
        return f"Montage livre d'or - {self.event} ({self.get_status_display()})"

    @property
    def is_ready(self):
        return self.status == self.Status.COMPLETED and bool(self.final_file)
