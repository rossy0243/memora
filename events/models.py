import secrets

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

from core.models import SiteConfiguration, format_price_amount


def event_cover_upload_path(instance, filename):
    return f"events/{instance.slug or 'pending'}/cover/{filename}"


def event_qr_code_upload_path(instance, filename):
    return f"events/{instance.slug or 'pending'}/qr/{filename}"


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
    event_date = models.DateField()
    location = models.CharField(max_length=255, blank=True)
    cover_image = models.ImageField(
        upload_to=event_cover_upload_path,
        blank=True,
        null=True,
    )
    welcome_message = models.TextField(blank=True)
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
    paid_at = models.DateTimeField(blank=True, null=True)
    payment_reference = models.CharField(max_length=120, blank=True)
    payment_provider = models.CharField(max_length=40, blank=True, default="manual")
    is_active = models.BooleanField(default=True)
    media_retention_days = models.PositiveIntegerField(default=7)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-event_date", "-created_at"]

    def __str__(self):
        return self.title

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
    def formatted_price(self):
        return format_price_amount(self.price_amount, self.price_currency)

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
                self.price_amount = site_configuration.event_price_amount
            if not self.price_currency:
                self.price_currency = site_configuration.event_price_currency
        if self.payment_status == self.PaymentStatus.PAID and not self.paid_at:
            self.paid_at = timezone.now()
        self.guest_access_code = self._normalize_guest_access_code(self.guest_access_code)
        super().save(*args, **kwargs)
        if self.payment_status == self.PaymentStatus.PAID:
            from accounts.services import record_event_commissions

            record_event_commissions(self)

    @classmethod
    def _generate_public_access_key(cls):
        while True:
            key = secrets.token_urlsafe(12).replace("_", "-")
            if not cls.objects.filter(public_access_key=key).exists():
                return key

    @staticmethod
    def _normalize_guest_access_code(code):
        return (code or "").strip().upper()
