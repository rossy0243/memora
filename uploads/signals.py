from django.db.models.signals import post_save
from django.dispatch import receiver

from events.models import Event

from .services import create_default_categories_for_event


@receiver(post_save, sender=Event)
def create_event_upload_categories(sender, instance, created, **kwargs):
    if created:
        create_default_categories_for_event(instance)
