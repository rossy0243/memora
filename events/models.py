import secrets
from datetime import datetime, time
from decimal import Decimal

from django.conf import settings
from django.core.cache import cache
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

from core.models import SiteConfiguration, format_price_amount


def event_cover_upload_path(instance, filename):
    return f"events/{instance.slug or 'pending'}/cover/{filename}"


def event_qr_code_upload_path(instance, filename):
    return f"events/{instance.slug or 'pending'}/qr/{filename}"


def event_custom_music_upload_path(instance, filename):
    return f"events/{instance.slug or 'pending'}/music/{filename}"


class EventType(models.Model):
    code = models.SlugField(max_length=40, unique=True)
    label = models.CharField(max_length=80)
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "label"]
        verbose_name = "type d'evenement"
        verbose_name_plural = "types d'evenements"

    def __str__(self):
        return self.label


class EventPlanQuerySet(models.QuerySet):
    """Invalide le cache des formules aussi sur les ecritures en masse.

    `update()` et `delete()` de queryset ne passent pas par `Model.save()` :
    sans cette surcharge, desactiver des formules en lot laisserait les pages
    publiques afficher l'ancienne liste jusqu'a expiration du cache.
    """

    def update(self, **kwargs):
        result = super().update(**kwargs)
        EventPlan._invalidate_cache()
        return result

    def delete(self, *args, **kwargs):
        result = super().delete(*args, **kwargs)
        EventPlan._invalidate_cache()
        return result


class EventPlan(models.Model):
    """Formule commerciale d'un evenement : un prix, un nombre d'invites annonce,
    et un quota de souvenirs.

    Le nombre d'invites est l'etiquette que comprend le client ; le quota de
    souvenirs est ce qui est reellement applique (c'est lui qui suit le cout de
    stockage, et il est mesurable, contrairement au nombre d'invites : les
    invites scannent un QR sans compte, on ne peut pas les compter de facon
    fiable). On ne bloque JAMAIS un invite parce qu'il arriverait « en trop ».
    """

    code = models.SlugField(max_length=40, unique=True)
    label = models.CharField(max_length=80)
    tagline = models.CharField(
        max_length=160,
        blank=True,
        help_text="Phrase courte affichee sous le nom de la formule.",
    )
    max_guests = models.PositiveIntegerField(
        default=0,
        help_text="Nombre d'invités annoncé, pour l'affichage. 0 = sans limite affichée.",
    )
    upload_quota = models.PositiveIntegerField(
        default=0,
        help_text=(
            "Nombre de souvenirs (photos + vidéos) inclus. C'est la limite réellement "
            "appliquée. 0 = utiliser la limite globale du site."
        ),
    )
    price_amount = models.PositiveIntegerField(
        default=0,
        help_text="Prix en centimes. Exemple : 7900 pour 79 USD. 0 = prix global du site.",
    )
    requires_quote = models.BooleanField(
        default=False,
        help_text=(
            "Prix sur devis : masque le prix (affiche « Sur devis ») et retire cette "
            "formule du formulaire de creation en libre-service. A creer/attacher "
            "manuellement depuis l'admin apres discussion du tarif avec le client."
        ),
    )
    includes_guestbook = models.BooleanField(
        default=False,
        help_text=(
            "Cette formule inclut le livre d'or video (agent(s) Memora a l'entree). "
            "Affichage uniquement : l'assignation reelle d'un agent reste manuelle "
            "en admin, sans blocage technique lie a la formule."
        ),
    )
    guestbook_agents_included = models.PositiveSmallIntegerField(
        default=0,
        help_text=(
            "Nombre d'agents Memora inclus, pour l'affichage (ex. 1 pour Grand jour, "
            "plus pour Prestige). Sans effet si « inclut le livre d'or » est decoche."
        ),
    )
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    is_default = models.BooleanField(
        default=False,
        help_text="Formule pre-selectionnee a la creation d'un evenement.",
    )

    objects = EventPlanQuerySet.as_manager()

    class Meta:
        ordering = ["sort_order", "price_amount", "label"]
        verbose_name = "formule"
        verbose_name_plural = "formules"

    def __str__(self):
        return self.label

    @property
    def effective_price_amount(self):
        if self.price_amount:
            return self.price_amount
        return SiteConfiguration.current().event_price_amount

    @property
    def effective_upload_quota(self):
        if self.upload_quota:
            return self.upload_quota
        return settings.MEMORA_EVENT_UPLOAD_LIMIT

    @property
    def formatted_price(self):
        return format_price_amount(
            self.effective_price_amount, SiteConfiguration.current().event_price_currency
        )

    @property
    def guests_label(self):
        if not self.max_guests:
            return "Invités illimités"
        return f"Jusqu'à {self.max_guests} invités"

    @property
    def guestbook_feature_label(self):
        """Phrase d'affichage pour le livre d'or, vide si non inclus."""
        if not self.includes_guestbook:
            return ""
        if self.guestbook_agents_included > 1:
            return "Livre d'or vidéo, plusieurs agents Memora inclus"
        return "Livre d'or vidéo, agent Memora inclus"

    @classmethod
    def default_plan(cls):
        active = cls.objects.filter(is_active=True)
        return active.filter(is_default=True).first() or active.first()

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Une seule formule par defaut.
        if self.is_default:
            EventPlan.objects.filter(is_default=True).exclude(pk=self.pk).update(is_default=False)
        self._invalidate_cache()

    def delete(self, *args, **kwargs):
        super().delete(*args, **kwargs)
        self._invalidate_cache()

    @staticmethod
    def _invalidate_cache():
        from core.context_processors import ACTIVE_PLANS_CACHE_KEY

        cache.delete(ACTIVE_PLANS_CACHE_KEY)


class Event(models.Model):
    class PaymentStatus(models.TextChoices):
        PENDING = "pending", "En attente"
        PAID = "paid", "Paye"
        FAILED = "failed", "Echec"
        REFUNDED = "refunded", "Rembourse"

    organizer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="events",
    )
    title = models.CharField(max_length=160)
    slug = models.SlugField(max_length=180, unique=True, blank=True)
    public_access_key = models.SlugField(max_length=32, unique=True, blank=True)
    couple_name = models.CharField(max_length=160, blank=True)
    event_type = models.ForeignKey(
        EventType,
        on_delete=models.PROTECT,
        related_name="events",
    )
    plan = models.ForeignKey(
        EventPlan,
        on_delete=models.PROTECT,
        related_name="events",
        blank=True,
        null=True,
        help_text="Formule choisie : fixe le prix et le quota de souvenirs.",
    )
    event_date = models.DateField()
    location = models.CharField(max_length=255, blank=True)
    cover_image = models.ImageField(
        upload_to=event_cover_upload_path,
        blank=True,
        null=True,
    )
    welcome_message = models.TextField(blank=True)
    selected_music_track = models.ForeignKey(
        "processing.MusicTrack",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="selected_for_events",
        help_text=(
            "Piste choisie a la main pour le film de cet evenement (par l'equipe Memora, "
            "ou l'organisateur si on le lui ouvre un jour). Remplace le choix automatique "
            "par ambiance, qui ne peut plus vraiment varier depuis que l'invite ne choisit "
            "plus de moment."
        ),
    )
    custom_music_file = models.FileField(
        upload_to=event_custom_music_upload_path,
        blank=True,
        null=True,
        help_text=(
            "Musique fournie par l'organisateur lui-meme : prioritaire sur tout choix "
            "automatique ou manuel. L'organisateur est seul responsable des droits sur "
            "ce fichier (voir CGU, section Contenus)."
        ),
    )
    custom_music_bpm = models.FloatField(
        null=True,
        blank=True,
        help_text="Tempo mesure automatiquement a l'upload. Sert au calage des coupes.",
    )
    custom_music_first_beat_offset = models.FloatField(
        default=0.0,
        help_text="Decalage du premier temps fort, en secondes.",
    )
    guest_access_code = models.CharField(
        max_length=24,
        blank=True,
        help_text="Code optionnel a donner uniquement aux invites presents.",
    )
    qr_code_image = models.ImageField(
        upload_to=event_qr_code_upload_path,
        blank=True,
        null=True,
    )
    payment_status = models.CharField(
        max_length=24,
        choices=PaymentStatus.choices,
        default=PaymentStatus.PENDING,
    )
    price_amount = models.PositiveIntegerField(default=0)
    price_currency = models.CharField(max_length=3, blank=True, default="")
    full_price_amount = models.PositiveIntegerField(
        default=0,
        help_text="Prix avant remise, en centimes. Egal au prix paye s'il n'y a pas de remise.",
    )
    discount_amount = models.PositiveIntegerField(
        default=0,
        help_text="Remise appliquee, en centimes.",
    )
    discount_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0"),
        help_text="Taux de remise applique, fige a la creation.",
    )
    promo_code = models.CharField(
        max_length=12,
        blank=True,
        default="",
        help_text="Code ambassadeur utilise pour la remise de bienvenue.",
    )
    paid_at = models.DateTimeField(blank=True, null=True)
    payment_reference = models.CharField(max_length=120, blank=True)
    payment_provider = models.CharField(max_length=40, blank=True, default="manual")
    receipt_sent_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="Date d'envoi du recu de paiement a l'organisateur. Vide = pas encore envoye.",
    )
    retention_reminder_sent_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="Rappel envoye a l'organisateur avant le retrait de ses souvenirs bruts. Vide = pas encore envoye.",
    )
    deliverable_reminder_sent_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="Rappel envoye a l'organisateur avant la suppression definitive de son film. Vide = pas encore envoye.",
    )
    is_active = models.BooleanField(default=True)
    guest_preview_enabled = models.BooleanField(
        "ouvert aux invités avant la date (test)",
        default=False,
        help_text=(
            "Réservé aux essais de l'équipe : ouvre la collecte aux invités avant le jour "
            "de l'événement (par défaut, le lien affiche « Rendez-vous le … » jusqu'à la "
            "date). À retirer une fois le test terminé."
        ),
    )
    guest_opening_time = models.TimeField(
        "heure d'ouverture du QR code",
        blank=True,
        null=True,
        help_text=(
            "Heure (le jour de l'événement) à partir de laquelle les invités peuvent prendre des "
            "photos et vidéos avec le QR code. Vide = dès minuit."
        ),
    )
    media_retention_days = models.PositiveIntegerField(default=7)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-event_date", "-created_at"]

    def __str__(self):
        return self.title

    @property
    def guestbook_is_open(self):
        """Vrai tant qu'au moins un agent est en mission : demarree, pas cloturee."""
        return self.guestbook_assignments.filter(
            started_at__isnull=False, ended_at__isnull=True
        ).exists()

    def get_public_url(self):
        return reverse(
            "public_event",
            kwargs={
                "slug": self.slug,
                "access_key": self.public_access_key,
            },
        )

    def get_public_movie_url(self):
        return reverse(
            "public_movie",
            kwargs={
                "slug": self.slug,
                "access_key": self.public_access_key,
            },
        )

    def get_event_type_display(self):
        return self.event_type.label

    @property
    def is_paid(self):
        return self.payment_status == self.PaymentStatus.PAID

    @property
    def can_accept_guest_uploads(self):
        return self.is_active and self.is_paid

    @property
    def guest_opens_at(self):
        """Moment (fuseau du site) ou la collecte s'ouvre : le jour J a l'heure choisie par
        l'organisateur, sinon a minuit."""
        return timezone.make_aware(datetime.combine(self.event_date, self.guest_opening_time or time.min))

    @property
    def is_upcoming_for_agent(self):
        """Le stand de l'agent du livre d'or s'ouvre le jour J des minuit, quelle que soit
        l'heure d'ouverture choisie pour les invites (l'agent arrive avant eux)."""
        return not self.guest_preview_enabled and timezone.localdate() < self.event_date

    @property
    def is_upcoming(self):
        """Vrai tant que l'ouverture (jour J, a l'heure choisie) n'est pas arrivee : la
        collecte est payee mais pas encore ouverte aux invites. L'equipe peut l'ouvrir
        avant l'heure pour un essai (`guest_preview_enabled`)."""
        return not self.guest_preview_enabled and timezone.now() < self.guest_opens_at

    @property
    def formatted_price(self):
        return format_price_amount(self.price_amount, self.price_currency)

    @property
    def upload_quota(self):
        """Nombre de souvenirs inclus. Suit la formule, sinon la limite globale."""
        if self.plan_id:
            return self.plan.effective_upload_quota
        return settings.MEMORA_EVENT_UPLOAD_LIMIT

    @property
    def upload_hard_limit(self):
        """Plafond reel accepte : le quota plus une marge de tolerance.

        La marge evite d'humilier un invite (et l'organisateur) en pleine fete
        pour quelques souvenirs de trop : on encaisse le depassement, on alerte
        l'organisateur, et on ne bloque qu'au-dela.
        """
        quota = self.upload_quota
        grace = SiteConfiguration.current().upload_quota_grace_percent
        return quota + int(quota * grace / 100)

    def uploads_used(self):
        return self.guest_uploads.filter(is_deleted=False).count()

    @property
    def upload_quota_state(self):
        """Etat du quota, pour le tableau de bord et les relances d'upsell."""
        quota = self.upload_quota
        used = self.uploads_used()
        percent = int(used * 100 / quota) if quota else 0
        return {
            "quota": quota,
            "used": used,
            "remaining": max(quota - used, 0),
            "percent": min(percent, 100),
            "is_reached": used >= quota,
            "is_hard_blocked": used >= self.upload_hard_limit,
            "is_nearly_reached": percent >= 80,
        }

    def mark_paid(self, reference="", provider="manual"):
        self.payment_status = self.PaymentStatus.PAID
        self.paid_at = self.paid_at or timezone.now()
        self.payment_reference = reference or self.payment_reference
        self.payment_provider = provider or self.payment_provider or "manual"

    @property
    def requires_guest_access_code(self):
        return bool(self.guest_access_code)

    def check_guest_access_code(self, code):
        return self._normalize_guest_access_code(code) == self.guest_access_code

    def measure_custom_music_tempo(self, save=True):
        """Mesure le tempo de la musique personnalisee (best-effort), meme logique
        que MusicTrack.measure_and_store_tempo : un tempo non mesure ne bloque rien,
        le montage retombe simplement sans calage sur le rythme."""
        from processing.tempo import measure_tempo

        if not self.custom_music_file:
            return False
        try:
            local_path = self._materialize_custom_music_to_temp()
        except Exception:
            return False
        try:
            bpm, offset = measure_tempo(local_path)
        except Exception:
            return False
        finally:
            local_path.unlink(missing_ok=True)

        self.custom_music_bpm = bpm
        self.custom_music_first_beat_offset = offset
        if save:
            self.save(update_fields=["custom_music_bpm", "custom_music_first_beat_offset", "updated_at"])
        return True

    def _materialize_custom_music_to_temp(self):
        """Copie le fichier (local ou R2) vers un fichier temporaire lisible par ffmpeg."""
        import tempfile
        from pathlib import Path

        suffix = Path(self.custom_music_file.name).suffix or ".audio"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temporary:
            temporary_path = Path(temporary.name)
            self.custom_music_file.open("rb")
            try:
                for chunk in self.custom_music_file.chunks():
                    temporary.write(chunk)
            finally:
                self.custom_music_file.close()
        return temporary_path

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.title)[:150] or "evenement"
            slug = base_slug
            counter = 2
            while Event.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                suffix = f"-{counter}"
                slug = f"{base_slug[: 180 - len(suffix)]}{suffix}"
                counter += 1
            self.slug = slug
        if not self.public_access_key:
            self.public_access_key = self._generate_public_access_key()
        if not self.price_amount or not self.price_currency:
            site_configuration = SiteConfiguration.current()
            if not self.price_amount:
                # La formule fixe le prix ; a defaut, le prix global du site.
                self.full_price_amount = (
                    self.plan.effective_price_amount
                    if self.plan_id
                    else site_configuration.event_price_amount
                )
                self._apply_first_event_discount(site_configuration)
            if not self.price_currency:
                self.price_currency = site_configuration.event_price_currency
        if self.payment_status == self.PaymentStatus.PAID and not self.paid_at:
            self.paid_at = timezone.now()
        self.guest_access_code = self._normalize_guest_access_code(self.guest_access_code)
        super().save(*args, **kwargs)
        if self.payment_status == self.PaymentStatus.PAID:
            from accounts.services import record_event_commissions

            record_event_commissions(self)

    def _apply_first_event_discount(self, site_configuration):
        """Fige le prix de l'evenement, remise de bienvenue comprise si elle est due.

        La remise n'est calculee qu'a la creation : le prix annonce a
        l'organisateur ne doit plus bouger ensuite.
        """
        self.price_amount = self.full_price_amount
        if not self.organizer_id:
            return

        from accounts.models import OrganizerProfile

        profile = OrganizerProfile.for_user(self.organizer)
        if not profile.is_eligible_for_first_event_discount(exclude_event_pk=self.pk):
            return

        discount = site_configuration.first_event_discount_amount(self.full_price_amount)
        if not discount:
            return

        self.discount_percent = site_configuration.first_event_discount_percent
        self.discount_amount = discount
        self.price_amount = max(self.full_price_amount - discount, 0)
        if not self.promo_code:
            self.promo_code = OrganizerProfile.for_user(profile.referred_by).referral_code

    @property
    def has_discount(self):
        return bool(self.discount_amount)

    @property
    def formatted_full_price(self):
        return format_price_amount(
            self.full_price_amount or self.price_amount, self.price_currency
        )

    @property
    def formatted_discount(self):
        return format_price_amount(self.discount_amount, self.price_currency)

    @classmethod
    def _generate_public_access_key(cls):
        while True:
            key = secrets.token_urlsafe(12).replace("_", "-")
            if not cls.objects.filter(public_access_key=key).exists():
                return key

    @staticmethod
    def _normalize_guest_access_code(code):
        return (code or "").strip().upper()
