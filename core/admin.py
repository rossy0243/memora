from django.contrib import admin

from .models import SiteConfiguration


@admin.register(SiteConfiguration)
class SiteConfigurationAdmin(admin.ModelAdmin):
    fields = ("event_price_amount", "event_price_currency", "updated_at")
    list_display = ("__str__", "formatted_event_price", "updated_at")
    readonly_fields = ("updated_at",)

    def has_add_permission(self, request):
        return not SiteConfiguration.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
