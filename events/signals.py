from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Event


@receiver(post_save, sender=Event)
def notify_owner_of_new_event(sender, instance, created, **kwargs):
    """Previent le proprietaire (WhatsApp) qu'un evenement vient d'etre cree, une fois la transaction validee."""
    if not created or kwargs.get("raw"):
        return
    from core import notifications

    transaction.on_commit(lambda: notifications.notify_event_created(instance))
