import logging

from django.db import models

logger = logging.getLogger(__name__)


def generated_movie_upload_path(instance, filename):
    event_slug = instance.event.slug if instance.event_id else "pending"
    return f"events/{event_slug}/movies/{filename}"


def music_track_upload_path(instance, filename):
    return f"music/{filename}"


class MusicTrack(models.Model):
    """Piste de la bibliotheque musicale, gerable depuis l'admin.

    La licence releve de l'administrateur qui televerse la piste : les champs
    d'attribution / source servent a garder une trace du droit d'usage.
    """

    class Mood(models.TextChoices):
        ROMANTIC = "romantic_cinematic", "Romantique / cinematique"
        EMOTIONAL = "cinematic_emotional", "Emotion / recueillement"
        JOYFUL = "joyful_party", "Joyeux / fete"
        WARM = "warm_lounge", "Chaleureux / lounge"
        ELEGANT = "elegant_warm", "Elegant / neutre"

    title = models.CharField(max_length=160)
    audio_file = models.FileField(upload_to=music_track_upload_path)
    mood = models.CharField(max_length=32, choices=Mood.choices, default=Mood.ELEGANT)
    bpm = models.FloatField(
        null=True,
        blank=True,
        help_text="Tempo mesure automatiquement a l'upload. Sert au calage des coupes.",
    )
    first_beat_offset = models.FloatField(
        default=0.0,
        help_text="Decalage du premier temps fort, en secondes.",
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Seules les pistes actives sont utilisees dans les films.",
    )
    attribution = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Credit a afficher si la licence l'exige (ex. CC-BY).",
    )
    source = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Provenance et licence, pour vos archives (ex. Pixabay, YouTube Audio Library).",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["mood", "title"]
        verbose_name = "piste musicale"
        verbose_name_plural = "bibliotheque musicale"

    def __str__(self):
        return f"{self.title} ({self.get_mood_display()})"

    @property
    def beat_interval(self):
        return 60.0 / self.bpm if self.bpm else 0.0

    def measure_and_store_tempo(self, save=True):
        """Mesure le tempo depuis le fichier (best-effort). Renvoie True si mesure."""
        from .tempo import measure_tempo

        if not self.audio_file:
            return False
        try:
            local_path = self._materialize_to_temp()
        except Exception as exc:  # fichier illisible / storage indisponible
            logger.warning("Music track materialisation failed pk=%s error=%s", self.pk, exc)
            return False
        try:
            bpm, offset = measure_tempo(local_path)
        except Exception as exc:  # ffmpeg absent ou decodage impossible
            logger.warning("Tempo measurement failed pk=%s error=%s", self.pk, exc)
            return False
        finally:
            local_path.unlink(missing_ok=True)

        self.bpm = bpm
        self.first_beat_offset = offset
        if save:
            super().save(update_fields=["bpm", "first_beat_offset", "updated_at"])
        return True

    def _materialize_to_temp(self):
        """Copie le fichier (local ou R2) vers un fichier temporaire lisible par ffmpeg."""
        import tempfile
        from pathlib import Path

        suffix = Path(self.audio_file.name).suffix or ".audio"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temporary:
            temporary_path = Path(temporary.name)
            self.audio_file.open("rb")
            try:
                for chunk in self.audio_file.chunks():
                    temporary.write(chunk)
            finally:
                self.audio_file.close()
        return temporary_path


class GeneratedMovie(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "En attente"
        PROCESSING = "processing", "En cours"
        COMPLETED = "completed", "Terminé"
        FAILED = "failed", "Échec"

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
    # Film heros : court et dense, c'est le livrable principal montre a l'organisateur.
    final_file = models.FileField(
        upload_to=generated_movie_upload_path,
        blank=True,
        null=True,
    )
    # Version integrale : tous les souvenirs retenus, pour ceux qui veulent tout revoir.
    full_file = models.FileField(
        upload_to=generated_movie_upload_path,
        blank=True,
        null=True,
    )
    # Teaser vertical 9:16, pense pour le partage sur mobile et les reseaux.
    teaser_file = models.FileField(
        upload_to=generated_movie_upload_path,
        blank=True,
        null=True,
    )
    full_duration = models.DurationField(blank=True, null=True)
    teaser_duration = models.DurationField(blank=True, null=True)
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
        COMPLETED = "completed", "Terminé"
        FAILED = "failed", "Échec"

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
