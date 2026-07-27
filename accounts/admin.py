from django.contrib import admin
from django.utils import timezone

from .models import CommissionLedger, OrganizerProfile, PayoutRequest


@admin.register(OrganizerProfile)
class OrganizerProfileAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "is_ambassador",
        "tier",
        "paid_events_count",
        "referral_code",
        "referred_by",
        "affiliation_state",
        "first_event_discount_used_at",
        "became_ambassador_at",
    )
    list_filter = ("is_ambassador", "tier")
    list_editable = ("is_ambassador",)
    search_fields = ("user__username", "user__email", "referral_code")
    readonly_fields = (
        "referral_code",
        "became_ambassador_at",
        "tier",
        "tier_updated_at",
        "affiliation_state",
        "created_at",
        "updated_at",
    )
    actions = (
        "grant_ambassador",
        "revoke_ambassador",
        "recompute_tier",
        "restart_affiliation",
        "reset_welcome_discount",
    )

    @admin.display(description="Événements payés")
    def paid_events_count(self, obj):
        return obj.paid_events_count()

    @admin.display(description="Affiliation")
    def affiliation_state(self, obj):
        if not obj.referred_by_id:
            return "—"
        expires_at = obj.referral_expires_at
        if expires_at is None:
            return "À vie"
        if obj.referral_is_active:
            return f"Active, {obj.referral_days_remaining} j restants (fin {expires_at:%d/%m/%Y})"
        return f"Expirée le {expires_at:%d/%m/%Y}"

    @admin.action(description="Redémarrer l'affiliation (repart pour la durée complète)")
    def restart_affiliation(self, request, queryset):
        restarted = queryset.filter(referred_by__isnull=False).update(
            referred_at=timezone.now()
        )
        self.message_user(request, f"{restarted} affiliation(s) redémarrée(s).")

    @admin.action(description="Rendre la remise de bienvenue")
    def reset_welcome_discount(self, request, queryset):
        reset = queryset.update(first_event_discount_used_at=None)
        self.message_user(request, f"Remise de bienvenue rendue à {reset} organisateur(s).")

    @admin.action(description="Accorder le statut ambassadeur")
    def grant_ambassador(self, request, queryset):
        granted = 0
        for profile in queryset.filter(is_ambassador=False):
            profile.grant_ambassador()
            profile.save(update_fields=["is_ambassador", "became_ambassador_at", "updated_at"])
            granted += 1
        self.message_user(request, f"{granted} ambassadeur(s) accordé(s).")

    @admin.action(description="Retirer le statut ambassadeur")
    def revoke_ambassador(self, request, queryset):
        revoked = 0
        for profile in queryset.filter(is_ambassador=True):
            profile.revoke_ambassador()
            profile.save(update_fields=["is_ambassador", "updated_at"])
            revoked += 1
        # Les commissions deja acquises restent dues : on ne reecrit pas le passe.
        self.message_user(
            request,
            f"{revoked} statut(s) retire(s). Les commissions deja acquises restent inchangees.",
        )

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


@admin.register(PayoutRequest)
class PayoutRequestAdmin(admin.ModelAdmin):
    list_display = (
        "beneficiary",
        "formatted_amount",
        "method",
        "payout_details",
        "status",
        "requested_at",
        "processed_at",
    )
    list_filter = ("status", "method", "requested_at")
    search_fields = ("beneficiary__username", "beneficiary__email", "payout_details")
    readonly_fields = ("beneficiary", "amount", "currency", "requested_at", "processed_at")
    actions = ("approve_requests", "mark_requests_paid", "reject_requests")

    fieldsets = (
        (
            "Demande",
            {
                "fields": (
                    "beneficiary",
                    "amount",
                    "currency",
                    "method",
                    "payout_details",
                    "requested_at",
                )
            },
        ),
        (
            "Traitement",
            {
                "description": (
                    "« Marquer payée » bascule aussi les commissions rattachées en payées. "
                    "« Refuser » les remet à disposition de l'ambassadeur."
                ),
                "fields": ("status", "admin_note", "processed_at"),
            },
        ),
    )

    @admin.display(description="Montant")
    def formatted_amount(self, obj):
        return obj.formatted_amount

    @admin.action(description="Approuver (versement à effectuer)")
    def approve_requests(self, request, queryset):
        updated = queryset.filter(status=PayoutRequest.Status.PENDING).update(
            status=PayoutRequest.Status.APPROVED
        )
        self.message_user(request, f"{updated} demande(s) approuvée(s).")

    @admin.action(description="Marquer payée(s) — solde les commissions")
    def mark_requests_paid(self, request, queryset):
        paid = 0
        for payout in queryset.exclude(status=PayoutRequest.Status.PAID):
            payout.mark_paid()
            paid += 1
        self.message_user(request, f"{paid} demande(s) versée(s) et commissions soldées.")

    @admin.action(description="Refuser — libère les commissions")
    def reject_requests(self, request, queryset):
        rejected = 0
        for payout in queryset.exclude(status=PayoutRequest.Status.PAID):
            payout.reject()
            rejected += 1
        self.message_user(
            request,
            f"{rejected} demande(s) refusée(s). Les commissions redeviennent disponibles.",
        )

    def has_add_permission(self, request):
        # Une demande naît du tableau de bord de l'ambassadeur, jamais de l'admin.
        return False
