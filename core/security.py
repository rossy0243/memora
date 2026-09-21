from ipaddress import ip_address

from django.conf import settings


def _clean_ip(value):
    candidate = (value or "").strip()
    if not candidate:
        return ""
    try:
        return str(ip_address(candidate))
    except ValueError:
        return ""


def get_client_ip(request):
    if getattr(settings, "MEMORA_TRUST_X_FORWARDED_FOR", False):
        # Derriere Cloudflare (Render), l'en-tete CF-Connecting-IP est pose par le proxy et ne peut pas
        # etre forge par le visiteur : on le prefere. Le premier element de X-Forwarded-For, lui, est
        # celui que le client envoie (falsifiable : contourne les limites par adresse).
        connecting_ip = _clean_ip(request.META.get("HTTP_CF_CONNECTING_IP", ""))
        if connecting_ip:
            return connecting_ip
        forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
        for value in forwarded_for.split(","):
            forwarded_ip = _clean_ip(value)
            if forwarded_ip:
                return forwarded_ip

    return _clean_ip(request.META.get("REMOTE_ADDR"))
