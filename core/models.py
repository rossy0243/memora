from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import DatabaseError, models


def format_price_amount(amount, currency):
    amount = amount or 0
    value = Decimal(amount) / Decimal("100")
    normalized_value = f"{value:.0f}" if amount % 100 == 0 else f"{value:.2f}"
    return f"{normalized_value} {currency}".strip()


class SiteConfiguration(models.Model):
    event_price_amount = models.PositiveIntegerField(
        default=settings.MEMORA_EVENT_PRICE_AMOUNT,
        validators=[MinValueValidator(1)],
        help_text="Montant en centimes. Exemple : 5900 pour 59 USD.",
    )
    event_price_currency = models.CharField(
        max_length=3,
        default=settings.MEMORA_EVENT_PRICE_CURRENCY,
        help_text="Code devise ISO sur 3 lettres, par exemple USD ou EUR.",
    )
    commission_starter_amount = models.PositiveIntegerField(
        default=settings.MEMORA_COMMISSION_STARTER_AMOUNT,
        help_text="Commission en centimes par événement payé pour le palier Starter. Exemple : 500 pour 5 USD.",
    )
    commission_medium_amount = models.PositiveIntegerField(
        default=settings.MEMORA_COMMISSION_MEDIUM_AMOUNT,
        help_text="Commission en centimes par événement payé pour le palier Medium. Exemple : 1000 pour 10 USD.",
    )
    commission_premium_amount = models.PositiveIntegerField(
        default=settings.MEMORA_COMMISSION_PREMIUM_AMOUNT,
        help_text="Commission en centimes par événement payé pour le palier Premium. Exemple : 2000 pour 20 USD.",
    )
    tier_medium_min_events = models.PositiveIntegerField(
        default=settings.MEMORA_TIER_MEDIUM_MIN_EVENTS,
        help_text="Nombre d'événements payés à partir duquel l'organisateur passe Medium. Exemple : 51.",
    )
    tier_premium_min_events = models.PositiveIntegerField(
        default=settings.MEMORA_TIER_PREMIUM_MIN_EVENTS,
        help_text="Nombre d'événements payés à partir duquel l'organisateur passe Premium. Exemple : 101.",
    )
    commission_referral_amount = models.PositiveIntegerField(
        default=settings.MEMORA_COMMISSION_REFERRAL_AMOUNT,
        help_text="Commission en centimes versée au parrain pour chaque événement payé d'un filleul. 0 pour désactiver.",
    )
    company_name = models.CharField(
        max_length=120,
        default="Memora",
        help_text="Nom commercial du produit, affiché partout (marque, pages légales).",
    )
    legal_entity_name = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text="Raison sociale de la société qui édite le service. Laisser vide pour reprendre le nom commercial.",
    )
    legal_contact_email = models.EmailField(
        blank=True,
        default="",
        help_text="Adresse e-mail de contact affichée sur les pages légales.",
    )
    legal_address = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Adresse postale ou siège social affiché sur les pages légales.",
    )
    legal_country = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Pays / juridiction dont relèvent les CGU (ex. France, Belgique).",
    )
    legal_registration_number = models.CharField(
        max_length=120,
        blank=True,
        default="",
        help_text="Numéro d'immatriculation de la société (ex. RCS Paris 000 000 000).",
    )
    legal_share_capital = models.CharField(
        max_length=60,
        blank=True,
        default="",
        help_text="Capital social, mention légale facultative (ex. 10 000 €).",
    )
    legal_publication_director = models.CharField(
        max_length=120,
        blank=True,
        default="",
        help_text="Directeur de la publication (mentions légales).",
    )
    hosting_provider = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text="Hébergeur du service, mentionné dans les mentions légales (ex. Render, OVH).",
    )
    payment_provider_name = models.CharField(
        max_length=120,
        blank=True,
        default="",
        help_text="Prestataire de paiement (ex. Stripe). Utilisé dans les CGU et la confidentialité.",
    )
    refund_window_days = models.PositiveIntegerField(
        default=14,
        help_text="Délai de rétractation / remboursement en jours, à adapter selon votre politique.",
    )
    data_protection_authority = models.CharField(
        max_length=160,
        blank=True,
        default="",
        help_text="Autorité de contrôle compétente (ex. la CNIL en France).",
    )
    cgu_effective_date = models.DateField(
        null=True,
        blank=True,
        help_text="Date d'entrée en vigueur des CGU. Vide = date du jour à l'affichage.",
    )
    privacy_effective_date = models.DateField(
        null=True,
        blank=True,
        help_text="Date d'entrée en vigueur de la politique de confidentialité. Vide = date du jour à l'affichage.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "configuration Memora"
        verbose_name_plural = "configuration Memora"

    def __str__(self):
        return "Configuration Memora"

    @property
    def formatted_event_price(self):
        return format_price_amount(self.event_price_amount, self.event_price_currency)

    def tier_for_paid_count(self, paid_count):
        """Palier (starter/medium/premium) pour le n-ième événement payé."""
        if paid_count >= self.tier_premium_min_events:
            return "premium"
        if paid_count >= self.tier_medium_min_events:
            return "medium"
        return "starter"

    def commission_amount_for_paid_count(self, paid_count):
        """Montant en centimes gagné pour le n-ième événement payé de l'organisateur."""
        tier = self.tier_for_paid_count(paid_count)
        return {
            "starter": self.commission_starter_amount,
            "medium": self.commission_medium_amount,
            "premium": self.commission_premium_amount,
        }[tier]

    @property
    def formatted_commission_starter(self):
        return format_price_amount(self.commission_starter_amount, self.event_price_currency)

    @property
    def formatted_commission_medium(self):
        return format_price_amount(self.commission_medium_amount, self.event_price_currency)

    @property
    def formatted_commission_premium(self):
        return format_price_amount(self.commission_premium_amount, self.event_price_currency)

    @property
    def formatted_commission_referral(self):
        return format_price_amount(self.commission_referral_amount, self.event_price_currency)

    @property
    def effective_legal_entity_name(self):
        return self.legal_entity_name.strip() or self.company_name

    @property
    def effective_data_protection_authority(self):
        return self.data_protection_authority.strip() or "l'autorité de protection des données compétente"

    def save(self, *args, **kwargs):
        self.event_price_currency = (self.event_price_currency or "").strip().upper()
        super().save(*args, **kwargs)

    @classmethod
    def current(cls):
        try:
            config = cls.objects.order_by("pk").first()
        except DatabaseError:
            config = None
        return config or cls(
            event_price_amount=settings.MEMORA_EVENT_PRICE_AMOUNT,
            event_price_currency=settings.MEMORA_EVENT_PRICE_CURRENCY,
        )
