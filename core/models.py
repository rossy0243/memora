from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.core.cache import cache
from django.core.validators import MinValueValidator
from django.db import DatabaseError, models

SITE_CONFIGURATION_CACHE_KEY = "memora:site_configuration"


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
    commission_mode = models.CharField(
        max_length=12,
        choices=[("percent", "Pourcentage du prix"), ("fixed", "Montant fixe")],
        default="percent",
        help_text=(
            "Mode de calcul des commissions. « Pourcentage » s'adapte automatiquement "
            "aux formules (un événement à 199 rapporte plus qu'un à 49)."
        ),
    )
    commission_starter_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("10.00"),
        help_text="Commission en % du prix de l'événement pour le palier Starter. Exemple : 10 pour 10 %.",
    )
    commission_medium_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("15.00"),
        help_text="Commission en % du prix de l'événement pour le palier Medium.",
    )
    commission_premium_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("20.00"),
        help_text="Commission en % du prix de l'événement pour le palier Premium.",
    )
    commission_referral_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("10.00"),
        help_text="Commission en % versée au parrain pour chaque événement payé d'un filleul. 0 pour désactiver.",
    )
    referral_duration_days = models.PositiveIntegerField(
        default=365,
        help_text=(
            "Durée d'une affiliation, en jours. Passé ce délai le filleul n'est plus "
            "rattaché à son parrain, qui cesse de toucher des commissions sur lui. "
            "0 = affiliation à vie."
        ),
    )
    minimum_payout_amount = models.PositiveIntegerField(
        default=2000,
        help_text="Montant minimum en centimes pour demander un retrait. Exemple : 2000 pour 20 USD.",
    )
    first_event_discount_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("15.00"),
        help_text=(
            "Remise en % accordée sur le PREMIER événement d'un organisateur venu avec "
            "le code d'un ambassadeur. 0 pour désactiver la remise."
        ),
    )
    upload_quota_grace_percent = models.PositiveSmallIntegerField(
        default=10,
        help_text=(
            "Marge de tolérance en % au-delà du quota de souvenirs de la formule, avant "
            "blocage réel. Évite de bloquer des invités en pleine fête. Exemple : 10."
        ),
    )
    commission_starter_amount = models.PositiveIntegerField(
        default=settings.MEMORA_COMMISSION_STARTER_AMOUNT,
        help_text="Commission en centimes par événement payé pour le palier Starter. Exemple : 500 pour 5 USD. Utilisé uniquement en mode « Montant fixe ».",
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

    @property
    def uses_percent_commissions(self):
        return self.commission_mode == "percent"

    def commission_percent_for_paid_count(self, paid_count):
        tier = self.tier_for_paid_count(paid_count)
        return {
            "starter": self.commission_starter_percent,
            "medium": self.commission_medium_percent,
            "premium": self.commission_premium_percent,
        }[tier]

    @staticmethod
    def _percent_of(price_amount, percent):
        """Applique un pourcentage a un montant en centimes.

        Arrondi commercial explicite (0,5 arrondi au superieur) : le defaut de
        Decimal est l'arrondi « banquier », qui surprendrait sur une facture.
        """
        if not price_amount or not percent:
            return 0
        raw = Decimal(price_amount) * Decimal(percent) / Decimal("100")
        return int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    def commission_amount_for_paid_count(self, paid_count, price_amount=None):
        """Montant en centimes gagné pour le n-ième événement payé de l'organisateur.

        En mode pourcentage, le montant dépend du prix de l'événement (donc de sa
        formule) : `price_amount` est alors requis pour un calcul exact ; sans lui
        on retombe sur le prix global du site, ce qui sert l'affichage.
        """
        if self.uses_percent_commissions:
            base = price_amount if price_amount is not None else self.event_price_amount
            return self._percent_of(base, self.commission_percent_for_paid_count(paid_count))
        tier = self.tier_for_paid_count(paid_count)
        return {
            "starter": self.commission_starter_amount,
            "medium": self.commission_medium_amount,
            "premium": self.commission_premium_amount,
        }[tier]

    @property
    def formatted_minimum_payout(self):
        return format_price_amount(self.minimum_payout_amount, self.event_price_currency)

    def first_event_discount_amount(self, price_amount):
        """Remise en centimes sur un prix donne. 0 si la remise est desactivee."""
        return self._percent_of(price_amount, self.first_event_discount_percent)

    @property
    def formatted_first_event_discount(self):
        percent = self.first_event_discount_percent or Decimal("0")
        return f"{percent.normalize():f} %"

    def referral_commission_amount(self, price_amount=None):
        """Montant en centimes versé au parrain pour un événement payé d'un filleul."""
        if self.uses_percent_commissions:
            base = price_amount if price_amount is not None else self.event_price_amount
            return self._percent_of(base, self.commission_referral_percent)
        return self.commission_referral_amount

    def _format_commission(self, amount, percent):
        if self.uses_percent_commissions:
            normalized = percent.normalize() if percent else Decimal("0")
            return f"{normalized:f} %"
        return format_price_amount(amount, self.event_price_currency)

    @property
    def formatted_commission_starter(self):
        return self._format_commission(self.commission_starter_amount, self.commission_starter_percent)

    @property
    def formatted_commission_medium(self):
        return self._format_commission(self.commission_medium_amount, self.commission_medium_percent)

    @property
    def formatted_commission_premium(self):
        return self._format_commission(self.commission_premium_amount, self.commission_premium_percent)

    @property
    def formatted_commission_referral(self):
        return self._format_commission(self.commission_referral_amount, self.commission_referral_percent)

    @property
    def effective_legal_entity_name(self):
        return self.legal_entity_name.strip() or self.company_name

    @property
    def effective_data_protection_authority(self):
        return self.data_protection_authority.strip() or "l'autorité de protection des données compétente"

    def save(self, *args, **kwargs):
        self.event_price_currency = (self.event_price_currency or "").strip().upper()
        super().save(*args, **kwargs)
        cache.delete(SITE_CONFIGURATION_CACHE_KEY)

    def delete(self, *args, **kwargs):
        super().delete(*args, **kwargs)
        cache.delete(SITE_CONFIGURATION_CACHE_KEY)

    @classmethod
    def current(cls):
        """Configuration du site, mise en cache : elle est relue a chaque requete
        (prix, textes legaux, en-tetes) et ne change qu'en admin."""
        config = cache.get(SITE_CONFIGURATION_CACHE_KEY)
        if config is not None:
            return config

        try:
            config = cls.objects.order_by("pk").first()
        except DatabaseError:
            # Base indisponible (migration en cours) : valeurs de repli, non cachees.
            return cls(
                event_price_amount=settings.MEMORA_EVENT_PRICE_AMOUNT,
                event_price_currency=settings.MEMORA_EVENT_PRICE_CURRENCY,
            )

        if config is None:
            config = cls(
                event_price_amount=settings.MEMORA_EVENT_PRICE_AMOUNT,
                event_price_currency=settings.MEMORA_EVENT_PRICE_CURRENCY,
            )
        cache.set(
            SITE_CONFIGURATION_CACHE_KEY,
            config,
            getattr(settings, "MEMORA_CONFIG_CACHE_SECONDS", 60),
        )
        return config
