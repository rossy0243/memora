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
