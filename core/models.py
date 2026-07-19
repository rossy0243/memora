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
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "configuration Memora"
        verbose_name_plural = "configuration Memora"

    def __str__(self):
        return "Configuration Memora"

    @property
    def formatted_event_price(self):
        return format_price_amount(self.event_price_amount, self.event_price_currency)

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
