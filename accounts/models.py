import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from .storage import identity_document_storage

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
    referred_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=(
            "Début de l'affiliation. Elle expire après la durée réglée dans la "
            "configuration Memora ; le parrain cesse alors de toucher des commissions."
        ),
    )
    tier_updated_at = models.DateTimeField(null=True, blank=True)
    terms_accepted_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Date d'acceptation des CGU a l'inscription. Preuve de consentement, ne pas modifier.",
    )
    first_event_discount_used_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=(
            "Date a laquelle la remise de bienvenue a ete consommee (premier evenement "
            "paye avec le code d'un ambassadeur). Vider pour la redonner."
        ),
    )
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

    @property
    def referrer_is_ambassador(self):
        """La remise et les commissions de parrainage supposent un parrain ambassadeur."""
        if not self.referred_by_id:
            return False
        return OrganizerProfile.for_user(self.referred_by).is_ambassador

    @property
    def referral_expires_at(self):
        """Fin de l'affiliation. None si pas de parrain ou affiliation a vie."""
        from core.models import SiteConfiguration

        if not self.referred_by_id:
            return None
        duration = SiteConfiguration.current().referral_duration_days
        if not duration:
            return None
        start = self.referred_at or self.created_at
        if not start:
            return None
        return start + timedelta(days=duration)

    @property
    def referral_is_active(self):
        """Vrai tant que l'affiliation court : au-dela, le filleul quitte son parrain."""
        if not self.referred_by_id:
            return False
        expires_at = self.referral_expires_at
        return expires_at is None or timezone.now() < expires_at

    @property
    def referral_days_remaining(self):
        expires_at = self.referral_expires_at
        if expires_at is None:
            return None
        return max((expires_at - timezone.now()).days, 0)

    def attach_referrer(self, referrer):
        """Rattache un parrain et demarre le compteur d'affiliation."""
        if self.referred_by_id or not referrer or referrer == self.user:
            return False
        self.referred_by = referrer
        self.referred_at = timezone.now()
        self.save(update_fields=["referred_by", "referred_at", "updated_at"])
        return True

    def is_eligible_for_first_event_discount(self, exclude_event_pk=None):
        """Vrai si le prochain evenement cree peut porter la remise de bienvenue.

        Conditions : un parrain ambassadeur, aucune remise deja consommee, aucun
        evenement deja paye, et aucun autre evenement en attente de paiement qui
        porte deja la remise (une seule a la fois).
        """
        from events.models import Event

        if self.first_event_discount_used_at or not self.referrer_is_ambassador:
            return False
        if self.paid_events_count():
            return False

        pending_with_discount = Event.objects.filter(
            organizer=self.user, discount_amount__gt=0
        ).exclude(payment_status=Event.PaymentStatus.PAID)
        if exclude_event_pk:
            pending_with_discount = pending_with_discount.exclude(pk=exclude_event_pk)
        return not pending_with_discount.exists()

    def consume_first_event_discount(self):
        if self.first_event_discount_used_at:
            return False
        self.first_event_discount_used_at = timezone.now()
        self.save(update_fields=["first_event_discount_used_at", "updated_at"])
        return True

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


def identity_document_upload_path(instance, filename):
    """Nom de fichier aleatoire (pas le nom d'origine) : evite qu'un scan de
    piece d'identite se retrouve indexe ou devinable via son nom de fichier."""
    import uuid
    from pathlib import Path

    extension = Path(filename).suffix.lower()
    return f"identity/{instance.organizer_id}/{uuid.uuid4().hex}{extension}"


class AmbassadorApplication(models.Model):
    """Candidature au statut Ambassadeur : numero de piece d'identite + scan.

    Volontairement separe de l'inscription (qui reste simple, sans piece
    d'identite) : seuls les organisateurs qui visent le statut Ambassadeur
    passent par ici, depuis leur tableau de bord. `tamper_risk_score` et
    `tamper_flags` sont des indices heuristiques (voir accounts.identity_check)
    qui aident l'administrateur a prioriser son examen — ils ne remplacent pas
    une decision humaine et ne bloquent jamais automatiquement une candidature.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "En attente"
        APPROVED = "approved", "Approuvée"
        REJECTED = "rejected", "Refusée"

    organizer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ambassador_applications",
    )
    id_document_number = models.CharField(
        max_length=60,
        help_text="Numéro de la pièce d'identité (carte d'identité, passeport...).",
    )
    id_document_file = models.FileField(
        upload_to=identity_document_upload_path,
        storage=identity_document_storage,
        help_text="Photo scannée ou photographiée de la pièce d'identité.",
    )
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    tamper_risk_score = models.PositiveSmallIntegerField(
        default=0,
        help_text=(
            "Indice heuristique 0-100 (métadonnées + analyse de recompression). "
            "N'est pas une preuve de fraude : sert à prioriser l'examen humain."
        ),
    )
    tamper_flags = models.JSONField(
        default=list,
        blank=True,
        help_text="Anomalies détectées automatiquement à la soumission, pour information.",
    )
    admin_note = models.CharField(max_length=300, blank=True, default="")
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    submitted_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "candidature ambassadeur"
        verbose_name_plural = "candidatures ambassadeur"
        ordering = ["-submitted_at"]

    def __str__(self):
        return f"{self.organizer.username} — {self.get_status_display()}"

    @property
    def risk_level(self):
        from .identity_check import risk_level_label

        return risk_level_label(self.tamper_risk_score)

    def approve(self, reviewer=None, note=""):
        self.status = self.Status.APPROVED
        self.reviewed_at = timezone.now()
        self.reviewed_by = reviewer
        if note:
            self.admin_note = note
        self.save(update_fields=["status", "reviewed_at", "reviewed_by", "admin_note"])

        profile = OrganizerProfile.for_user(self.organizer)
        profile.grant_ambassador()
        profile.save(update_fields=["is_ambassador", "became_ambassador_at", "updated_at"])

    def reject(self, reviewer=None, note=""):
        self.status = self.Status.REJECTED
        self.reviewed_at = timezone.now()
        self.reviewed_by = reviewer
        if note:
            self.admin_note = note
        self.save(update_fields=["status", "reviewed_at", "reviewed_by", "admin_note"])


class AgentProfile(models.Model):
    """Marque un compte comme agent Memora : employe qui anime le livre d'or
    video a l'entree d'un evenement. Distinct d'un organisateur : pas d'evenements
    a lui, juste des missions affectees via l'admin (voir guestbook.GuestBookAssignment).
    Plusieurs agents peuvent etre affectes au meme evenement, chacun avec son
    propre compte et son propre service.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="agent_profile",
    )
    phone_number = models.CharField(
        max_length=32,
        blank=True,
        help_text="Contact pratique pour coordonner une mission, facultatif.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "profil agent"
        verbose_name_plural = "profils agents"

    def __str__(self):
        return f"{self.user.username} (agent)"


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
    payout_request = models.ForeignKey(
        "accounts.PayoutRequest",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="commissions",
        help_text="Demande de retrait qui porte cette commission.",
    )
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


class PayoutRequest(models.Model):
    """Demande de retrait des gains d'un ambassadeur.

    Une demande fige les commissions en attente qui lui sont rattachees : elles
    ne peuvent pas etre demandees deux fois. Un refus les libere, un paiement
    les marque payees.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "En attente"
        APPROVED = "approved", "Approuvée"
        PAID = "paid", "Payée"
        REJECTED = "rejected", "Refusée"

    class Method(models.TextChoices):
        MOBILE_MONEY = "mobile_money", "Mobile Money"
        BANK_TRANSFER = "bank", "Virement bancaire"
        OTHER = "other", "Autre"

    beneficiary = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="payout_requests",
    )
    amount = models.PositiveIntegerField(help_text="Montant demande en centimes, fige a la demande.")
    currency = models.CharField(max_length=3)
    method = models.CharField(max_length=20, choices=Method.choices, default=Method.MOBILE_MONEY)
    payout_details = models.CharField(
        max_length=200,
        help_text="Numero Mobile Money, IBAN ou coordonnees de versement.",
    )
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    admin_note = models.CharField(max_length=300, blank=True, default="")
    requested_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "demande de retrait"
        verbose_name_plural = "demandes de retrait"
        ordering = ["-requested_at"]

    def __str__(self):
        return f"{self.beneficiary.username} - {self.formatted_amount} ({self.get_status_display()})"

    @property
    def formatted_amount(self):
        from core.models import format_price_amount

        return format_price_amount(self.amount, self.currency)

    @property
    def is_open(self):
        """Une demande ouverte bloque une nouvelle demande du meme beneficiaire."""
        return self.status in {self.Status.PENDING, self.Status.APPROVED}

    def mark_paid(self):
        """Verse la demande : les commissions rattachees passent en payees."""
        self.status = self.Status.PAID
        self.processed_at = timezone.now()
        self.save(update_fields=["status", "processed_at"])
        for entry in self.commissions.all():
            entry.mark_paid()
            entry.save(update_fields=["status", "paid_at"])

    def reject(self, note=""):
        """Refuse la demande et remet les commissions a disposition."""
        self.status = self.Status.REJECTED
        self.processed_at = timezone.now()
        if note:
            self.admin_note = note
        self.save(update_fields=["status", "processed_at", "admin_note"])
        self.commissions.update(payout_request=None)
