from hashlib import sha256
import math

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from core.security import get_client_ip


def event_access_session_key(event):
    return f"memora_event_access_{event.pk}"


def has_guest_access(request, event):
    if not event.requires_guest_access_code:
        return True
    return request.session.get(event_access_session_key(event)) is True


def grant_guest_access(request, event):
    if not request.session.session_key:
        request.session.create()
    request.session[event_access_session_key(event)] = True


def _guest_access_attempt_cache_key(request, event):
    if not request.session.session_key:
        request.session.create()
    identity = "|".join(
        [
            str(event.pk),
            get_client_ip(request) or "unknown-ip",
            request.session.session_key or "unknown-session",
        ]
    )
    digest = sha256(identity.encode("utf-8")).hexdigest()
    return f"memora_guest_access_attempts:{digest}"


def get_guest_access_lockout_error(request, event):
    state = cache.get(_guest_access_attempt_cache_key(request, event)) or {}
    locked_until = state.get("locked_until")
    if not locked_until:
        return ""

    remaining_seconds = int(locked_until - timezone.now().timestamp())
    if remaining_seconds <= 0:
        return ""

    remaining_minutes = max(1, math.ceil(remaining_seconds / 60))
    if remaining_minutes == 1:
        return "Trop de tentatives. Reessayez dans moins d'une minute."
    return f"Trop de tentatives. Reessayez dans {remaining_minutes} minutes."


def record_guest_access_failure(request, event):
    key = _guest_access_attempt_cache_key(request, event)
    now = timezone.now().timestamp()
    state = cache.get(key) or {}
    failures = int(state.get("failures", 0)) + 1
    locked_until = state.get("locked_until", 0)

    attempt_limit = max(1, settings.MEMORA_GUEST_ACCESS_ATTEMPT_LIMIT)
    lockout_seconds = max(1, settings.MEMORA_GUEST_ACCESS_LOCKOUT_SECONDS)
    if failures >= attempt_limit:
        multiplier = min(failures - attempt_limit + 1, 5)
        locked_until = now + (lockout_seconds * multiplier)

    cache.set(
        key,
        {"failures": failures, "locked_until": locked_until},
        timeout=max(lockout_seconds * 6, 300),
    )


def reset_guest_access_failures(request, event):
    cache.delete(_guest_access_attempt_cache_key(request, event))
