from django.contrib import admin

from .models import SiteConfiguration


@admin.register(SiteConfiguration)
class SiteConfigurationAdmin(admin.ModelAdmin):
    fieldsets = (
        (None, {"fields": ("event_price_amount", "event_price_currency", "updated_at")}),
        (
            "Commissions sur événements propres (par palier)",
            {
                "fields": (
                    "commission_starter_amount",
                    "commission_medium_amount",
                    "commission_premium_amount",
                    "tier_medium_min_events",
                    "tier_premium_min_events",
                )
            },
        ),
        ("Commission de parrainage", {"fields": ("commission_referral_amount",)}),
        (
            "Informations légales (CGU et confidentialité)",
            {
                "description": (
                    "Ces valeurs alimentent automatiquement les pages CGU et Politique de "
                    "confidentialité. Renseignez-les pour que les documents soient à jour."
                ),
                "fields": (
                    "company_name",
                    "legal_entity_name",
                    "legal_registration_number",
                    "legal_share_capital",
                    "legal_publication_director",
                    "legal_contact_email",
                    "legal_address",
                    "legal_country",
                    "hosting_provider",
                    "payment_provider_name",
                    "refund_window_days",
                    "data_protection_authority",
                    "cgu_effective_date",
                    "privacy_effective_date",
                ),
            },
        ),
    )
    list_display = (
        "__str__",
        "formatted_event_price",
        "formatted_commission_starter",
        "formatted_commission_medium",
        "formatted_commission_premium",
        "formatted_commission_referral",
        "updated_at",
    )
    readonly_fields = ("updated_at",)

    def has_add_permission(self, request):
        return not SiteConfiguration.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
