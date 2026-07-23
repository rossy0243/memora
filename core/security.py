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
        forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
        for value in forwarded_for.split(","):
            forwarded_ip = _clean_ip(value)
            if forwarded_ip:
                return forwarded_ip

    return _clean_ip(request.META.get("REMOTE_ADDR"))
