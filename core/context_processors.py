from urllib.parse import urljoin

from django.conf import settings
from django.core.cache import cache
from django.db import DatabaseError
from django.templatetags.static import static

from .models import SiteConfiguration


ACTIVE_PLANS_CACHE_KEY = "memora:active_event_plans"


def _active_event_plans():
    """Formules actives, pour les pages publiques.

    Mise en cache : ce context processor s'execute a CHAQUE requete, y compris
    sur la page d'accueil. Silencieux avant migration.
    """
    plans = cache.get(ACTIVE_PLANS_CACHE_KEY)
    if plans is not None:
        return plans

    try:
        from events.models import EventPlan

        plans = list(EventPlan.objects.filter(is_active=True))
    except (DatabaseError, ImportError):
        return []

    cache.set(
        ACTIVE_PLANS_CACHE_KEY,
        plans,
        getattr(settings, "MEMORA_CONFIG_CACHE_SECONDS", 60),
    )
    return plans


def _plan_price_range(plans):
    """Fourchette de prix affichable (« de 49 USD à 199 USD »)."""
    if not plans:
        return {"min": "", "max": ""}
    by_price = sorted(plans, key=lambda plan: plan.effective_price_amount)
    return {
        "min": by_price[0].formatted_price,
        "max": by_price[-1].formatted_price,
    }


def site_metadata(request):
    site_url = settings.MEMORA_PUBLIC_BASE_URL.rstrip("/")
    if not site_url and request:
        site_url = f"{request.scheme}://{request.get_host()}"

    path = request.path if request else "/"
    canonical_url = urljoin(f"{site_url}/", path.lstrip("/")) if site_url else path
    default_og_image = urljoin(f"{site_url}/", static("img/memora-hero.png").lstrip("/")) if site_url else static("img/memora-hero.png")

    site_configuration = SiteConfiguration.current()
    event_plans = _active_event_plans()

    return {
        "site_name": site_configuration.company_name or "Memora",
        "company_name": site_configuration.company_name or "Memora",
        "site_url": site_url,
        "canonical_url": canonical_url,
        "default_og_image": default_og_image,
        "memora_event_price": site_configuration.formatted_event_price,
        "memora_event_plans": event_plans,
        "memora_plan_price_range": _plan_price_range(event_plans),
        "memora_upload_grace_percent": site_configuration.upload_quota_grace_percent,
        "memora_commission_is_percent": site_configuration.uses_percent_commissions,
        "memora_commission_starter": site_configuration.formatted_commission_starter,
        "memora_commission_medium": site_configuration.formatted_commission_medium,
        "memora_commission_premium": site_configuration.formatted_commission_premium,
        "memora_commission_referral": site_configuration.formatted_commission_referral,
        "memora_tier_medium_min": site_configuration.tier_medium_min_events,
        "memora_tier_premium_min": site_configuration.tier_premium_min_events,
    }
