from django.contrib import admin

from .models import CommissionLedger, OrganizerProfile


@admin.register(OrganizerProfile)
class OrganizerProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "tier", "paid_events_count", "referral_code", "referred_by", "tier_updated_at")
    list_filter = ("tier",)
    search_fields = ("user__username", "user__email", "referral_code")
    readonly_fields = ("referral_code", "tier_updated_at", "created_at", "updated_at")
    actions = ("recompute_tier",)

    @admin.display(description="Événements payés")
    def paid_events_count(self, obj):
        return obj.paid_events_count()

    @admin.action(description="Recalculer le palier")
    def recompute_tier(self, request, queryset):
        changed = 0
        for profile in queryset:
            if profile.refresh_tier():
                changed += 1
        self.message_user(request, f"{changed} palier(s) mis à jour.")


@admin.register(CommissionLedger)
class CommissionLedgerAdmin(admin.ModelAdmin):
    list_display = ("beneficiary", "kind", "tier", "formatted_amount", "event", "status", "created_at", "paid_at")
    list_filter = ("status", "kind", "tier", "created_at")
    search_fields = ("beneficiary__username", "beneficiary__email", "event__title")
    readonly_fields = ("beneficiary", "event", "kind", "tier", "amount", "currency", "created_at")
    actions = ("mark_as_paid",)

    @admin.action(description="Marquer comme payée(s)")
    def mark_as_paid(self, request, queryset):
        updated = 0
        for entry in queryset.filter(status=CommissionLedger.Status.PENDING):
            entry.mark_paid()
            entry.save(update_fields=["status", "paid_at"])
            updated += 1
        self.message_user(request, f"{updated} commission(s) marquée(s) payée(s).")

    def has_add_permission(self, request):
        return False
