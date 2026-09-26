from django.contrib import admin, messages
from django.shortcuts import get_object_or_404, redirect
from django.urls import path, reverse
from django.views.decorators.http import require_POST

from uploads.models import UploadCategory

from core.models import SiteConfiguration
from guestbook.models import GuestBookAssignment

from .models import Event, EventPlan, EventType
from .services import (
    EventResetRefused,
    delete_event,
    purge_event_media,
    reset_event_content,
    send_payment_receipt_email,
)


@admin.register(EventPlan)
class EventPlanAdmin(admin.ModelAdmin):
    list_display = (
        "label",
        "code",
        "guests_label",
        "upload_quota",
        "formatted_price",
        "requires_quote",
        "includes_guestbook",
        "sort_order",
        "is_default",
        "is_active",
    )
    list_editable = ("upload_quota", "sort_order", "is_default", "is_active")
    list_filter = ("is_active", "requires_quote", "includes_guestbook")
    search_fields = ("label", "code")
    prepopulated_fields = {"code": ("label",)}
    fieldsets = (
        ("Formule", {"fields": ("label", "code", "tagline", "sort_order", "is_default", "is_active")}),
        (
            "Tarif et limites",
            {
                "fields": ("price_amount", "requires_quote", "max_guests", "upload_quota"),
                "description": (
                    "Le nombre d'invités est une étiquette commerciale. La limite réellement "
                    "appliquée est le quota de souvenirs : un invité n'est jamais bloqué "
                    "parce qu'il arriverait « en trop ». La marge de tolérance au-delà du "
                    "quota se règle dans la configuration Memora. « Sur devis » masque le "
                    "prix côté public et retire la formule du parcours de création en "
                    "libre-service (à attacher manuellement à l'événement une fois créé)."
                ),
            },
        ),
        (
            "Livre d'or",
            {
                "fields": ("includes_guestbook", "guestbook_agents_included"),
                "description": (
                    "Affichage uniquement : ces champs pilotent la promesse commerciale "
                    "montrée à l'organisateur (carte tarifs, choix de formule). "
                    "L'assignation réelle d'un agent reste manuelle et n'est pas bloquée "
                    "techniquement par cette limite."
                ),
            },
        ),
    )


@admin.register(EventType)
class EventTypeAdmin(admin.ModelAdmin):
    list_display = ("label", "code", "sort_order", "is_active")
    list_editable = ("sort_order", "is_active")
    list_filter = ("is_active",)
    search_fields = ("label", "code")
    prepopulated_fields = {"code": ("label",)}


class UploadCategoryInline(admin.TabularInline):
    model = UploadCategory
    extra = 0
    fields = ("label", "code", "sort_order", "is_active")
    prepopulated_fields = {"code": ("label",)}


class GuestBookAssignmentInline(admin.TabularInline):
    model = GuestBookAssignment
    extra = 0
    fields = ("agent", "started_at", "ended_at")
    autocomplete_fields = ("agent",)
    verbose_name = "agent affecte au livre d'or"
    verbose_name_plural = "Livre d'or — agents affectes (plusieurs possibles, chacun son service)"


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    inlines = [UploadCategoryInline, GuestBookAssignmentInline]
    actions = ("mark_events_paid", "open_for_guest_test", "close_guest_test", "purge_r2_files")
    change_form_template = "admin/events/event/change_form.html"
    list_display = (
        "title",
        "organizer",
        "event_type",
        "event_date",
        "guest_preview_enabled",
        "payment_status",
        "formatted_price",
        "paid_at",
        "is_active",
        "guestbook_agent_count",
        "guest_access_code",
        "media_retention_days",
        "created_at",
    )
    list_select_related = ("organizer", "event_type")
    list_filter = ("payment_status", "event_type", "is_active", "event_date", "created_at")
    search_fields = ("title", "couple_name", "location", "organizer__username", "payment_reference")
    prepopulated_fields = {"slug": ("title",)}
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("selected_music_track",)
    fieldsets = (
        (
            "Informations",
            {
                "fields": (
                    "organizer",
                    "title",
                    "slug",
                    "couple_name",
                    "event_type",
                    "event_date",
                    "location",
                )
            },
        ),
        (
            "Paiement",
            {
                "fields": (
                    "plan",
                    "payment_status",
                    "price_amount",
                    "price_currency",
                    "paid_at",
                    "payment_provider",
                    "payment_reference",
                ),
            },
        ),
        (
            "Experience invite",
            {
                "fields": (
                    "cover_image",
                    "welcome_message",
                    "guest_access_code",
                    "qr_code_image",
                    "is_active",
                    "guest_opening_time",
                    "guest_preview_enabled",
                    "remote_guestbook_enabled",
                )
            },
        ),
        (
            "Musique du film",
            {
                "fields": ("selected_music_track",),
                "description": (
                    "Facultatif : impose une piste precise pour le film de cet evenement. "
                    "Sans choix ici, Memora retombe sur une ambiance par defaut liee au type "
                    "d'evenement — l'invite ne choisissant plus de moment, ce choix automatique "
                    "ne peut plus vraiment varier d'un evenement a l'autre."
                ),
            },
        ),
        (
            "Retention",
            {
                "fields": ("media_retention_days",),
            },
        ),
        (
            "Dates",
            {
                "fields": ("created_at", "updated_at"),
            },
        ),
    )

    def get_queryset(self, request):
        from django.db.models import Count

        return super().get_queryset(request).annotate(_guestbook_agent_count=Count("guestbook_assignments"))

    @admin.display(description="Agents livre d'or", ordering="_guestbook_agent_count")
    def guestbook_agent_count(self, obj):
        return obj._guestbook_agent_count

    def get_fieldsets(self, request, obj=None):
        fieldsets = list(super().get_fieldsets(request, obj))
        current_price = SiteConfiguration.current().formatted_event_price
        payment_title, payment_options = fieldsets[1]
        fieldsets[1] = (
            payment_title,
            {
                **payment_options,
                "description": (
                    "Activation manuelle MVP : le prix de reference actuel est "
                    f"{current_price}. Marquez l'evenement comme paye apres verification du paiement."
                ),
            },
        )
        return fieldsets

    @admin.action(description="Marquer les evenements selectionnes comme payes")
    def mark_events_paid(self, request, queryset):
        updated = 0
        receipts_sent = 0
        for event in queryset:
            event.mark_paid(provider="manual-admin")
            event.save(update_fields=["payment_status", "paid_at", "payment_provider", "payment_reference", "updated_at"])
            updated += 1
            if send_payment_receipt_email(event):
                receipts_sent += 1
        self.message_user(
            request,
            f"{updated} evenement(s) marque(s) comme paye(s), {receipts_sent} recu(s) envoye(s) par e-mail.",
        )

    def _set_guest_preview(self, request, queryset, enabled):
        queryset.update(guest_preview_enabled=enabled)
        return queryset.count()

    @admin.action(description="Ouvrir aux invites pour test (avant la date)")
    def open_for_guest_test(self, request, queryset):
        count = self._set_guest_preview(request, queryset, True)
        self.message_user(
            request,
            f"{count} evenement(s) ouvert(s) aux invites pour test. Pensez a refermer le test ensuite.",
            level=messages.WARNING,
        )

    @admin.action(description="Refermer le test invites (retour a la date)")
    def close_guest_test(self, request, queryset):
        count = self._set_guest_preview(request, queryset, False)
        self.message_user(request, f"{count} evenement(s) : le lien attend a nouveau la date de l'evenement.")

    def get_urls(self):
        custom = [
            path(
                "<path:object_id>/basculer-test-invites/",
                self.admin_site.admin_view(require_POST(self.toggle_guest_test)),
                name="events_event_toggle_guest_test",
            ),
            path(
                "<path:object_id>/vider-contenu-test/",
                self.admin_site.admin_view(require_POST(self.reset_test_content)),
                name="events_event_reset_content",
            ),
        ]
        return custom + super().get_urls()

    def toggle_guest_test(self, request, object_id):
        """Bouton de la fiche evenement : ouvre ou referme le test avant la date."""
        event = get_object_or_404(Event, pk=object_id)
        if not self.has_change_permission(request, event):
            return redirect("admin:index")
        event.guest_preview_enabled = not event.guest_preview_enabled
        event.save(update_fields=["guest_preview_enabled", "updated_at"])
        if event.guest_preview_enabled:
            self.message_user(
                request,
                f"Ouvert aux invites pour test : {request.build_absolute_uri(event.get_public_url())} "
                "— pensez a refermer le test ensuite.",
                level=messages.WARNING,
            )
        else:
            self.message_user(request, "Test referme : le lien attend a nouveau la date de l'evenement.")
        return redirect(reverse("admin:events_event_change", args=[event.pk]))

    def reset_test_content(self, request, object_id):
        """Bouton de la fiche evenement : vide les souvenirs, films et livre d'or d'un test.

        L'evenement, son lien et son QR code ne changent pas : on peut refaire un essai
        avec le meme QR imprime.
        """
        event = get_object_or_404(Event, pk=object_id)
        change_url = reverse("admin:events_event_change", args=[event.pk])
        if not self.has_delete_permission(request, event):
            return redirect("admin:index")
        if request.POST.get("confirm") != "VIDER":
            self.message_user(request, "Confirmation absente : rien n'a ete supprime.", level=messages.WARNING)
            return redirect(change_url)
        try:
            counts = reset_event_content(event)
        except EventResetRefused as exc:
            self.message_user(request, str(exc), level=messages.ERROR)
            return redirect(change_url)
        self.message_user(
            request,
            f"Contenu de test supprime : {counts['uploads']} souvenir(s), {counts['movies']} film(s), "
            f"{counts['guestbook_messages']} message(s) livre d'or"
            f"{' + le montage' if counts['guestbook_movie'] else ''}. "
            "L'evenement et son QR code sont inchanges.",
        )
        return redirect(change_url)

    @admin.action(description="Purger les fichiers R2 (garder l'evenement)")
    def purge_r2_files(self, request, queryset):
        totals = {"uploads": 0, "guestbook": 0, "deliverables": 0, "event": 0}
        for event in queryset:
            counts = purge_event_media(event)
            for key, value in counts.items():
                totals[key] += value
        self.message_user(
            request,
            "Fichiers R2 supprimes : "
            f"{totals['uploads']} upload(s), {totals['guestbook']} message(s) livre d'or, "
            f"{totals['deliverables']} livrable(s), {totals['event']} image(s) d'evenement. "
            "Les evenements sont conserves.",
        )

    # La suppression d'un evenement (bouton et action « delete_selected »)
    # purge d'abord les fichiers R2, puis supprime les lignes dans l'ordre
    # (uploads avant l'evenement, sinon ProtectedError sur UploadCategory).
    def delete_model(self, request, obj):
        delete_event(obj)

    def delete_queryset(self, request, queryset):
        for event in list(queryset):
            delete_event(event)
