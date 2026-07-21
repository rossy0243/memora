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
