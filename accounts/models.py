import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone

REFERRAL_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def generate_referral_code():
    while True:
        code = "".join(secrets.choice(REFERRAL_CODE_ALPHABET) for _ in range(8))
        if not OrganizerProfile.objects.filter(referral_code=code).exists():
            return code


class OrganizerProfile(models.Model):
    class Tier(models.TextChoices):
        STARTER = "starter", "Starter"
        MEDIUM = "medium", "Medium"
        PREMIUM = "premium", "Premium"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="organizer_profile",
    )
    is_ambassador = models.BooleanField(
        default=False,
        help_text=(
            "Statut accordé manuellement par Memora. Seuls les ambassadeurs "
            "perçoivent des commissions ; les autres sont des organisateurs simples."
        ),
    )
    became_ambassador_at = models.DateTimeField(null=True, blank=True)
    tier = models.CharField(
        max_length=20,
        choices=Tier.choices,
        default=Tier.STARTER,
        help_text="Palier calculé automatiquement d'après le nombre d'événements payés (ambassadeurs).",
    )
    referral_code = models.CharField(max_length=12, unique=True)
    referred_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="referred_profiles",
        help_text="Organisateur dont le code de parrainage a été utilisé à l'inscription.",
    )
    tier_updated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "profil organisateur"
        verbose_name_plural = "profils organisateurs"

    def __str__(self):
        if not self.is_ambassador:
            return f"{self.user.username} (organisateur)"
        return f"{self.user.username} (ambassadeur {self.get_tier_display()})"

    def grant_ambassador(self):
        if not self.is_ambassador:
            self.is_ambassador = True
            self.became_ambassador_at = timezone.now()

    def revoke_ambassador(self):
        self.is_ambassador = False

    def paid_events_count(self):
        from events.models import Event

        return Event.objects.filter(
            organizer=self.user,
            payment_status=Event.PaymentStatus.PAID,
        ).count()

    def refresh_tier(self, paid_count=None, save=True):
        """Recalcule le palier d'après le nombre d'événements payés. Renvoie True si changé."""
        from core.models import SiteConfiguration

        if paid_count is None:
            paid_count = self.paid_events_count()
        new_tier = SiteConfiguration.current().tier_for_paid_count(paid_count)
        if new_tier != self.tier:
            self.tier = new_tier
            self.tier_updated_at = timezone.now()
            if save and self.pk:
                self.save(update_fields=["tier", "tier_updated_at", "updated_at"])
            return True
        return False

    def save(self, *args, **kwargs):
        if not self.referral_code:
            self.referral_code = generate_referral_code()
        super().save(*args, **kwargs)

    @classmethod
    def for_user(cls, user):
        profile, _ = cls.objects.get_or_create(user=user)
        return profile


class CommissionLedger(models.Model):
    class Kind(models.TextChoices):
        OWN_EVENT = "own", "Événement propre"
        REFERRAL_EVENT = "referral", "Événement filleul"

    class Status(models.TextChoices):
        PENDING = "pending", "En attente"
        PAID = "paid", "Payée"

    beneficiary = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="commissions",
    )
    event = models.ForeignKey(
        "events.Event",
        on_delete=models.CASCADE,
        related_name="commissions",
    )
    kind = models.CharField(max_length=12, choices=Kind.choices)
    tier = models.CharField(
        max_length=20,
        blank=True,
        default="",
        help_text="Palier appliqué au moment du gain (commissions sur événement propre).",
    )
    amount = models.PositiveIntegerField(help_text="Montant en centimes, figé au moment du gain.")
    currency = models.CharField(max_length=3)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    note = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        verbose_name = "commission"
        verbose_name_plural = "commissions"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["event", "kind"], name="unique_commission_per_event_kind"),
        ]

    def __str__(self):
        return f"{self.beneficiary.username} - {self.get_kind_display()} - {self.formatted_amount}"

    @property
    def formatted_amount(self):
        from core.models import format_price_amount

        return format_price_amount(self.amount, self.currency)

    def mark_paid(self):
        self.status = self.Status.PAID
        self.paid_at = self.paid_at or timezone.now()
