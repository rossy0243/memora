from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import OrganizerProfile


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_organizer_profile(sender, instance, created, **kwargs):
    # `raw` = chargement d'une sauvegarde (loaddata) : le profil est deja dans le fichier, le recreer
    # ici provoquerait un conflit et rendrait la restauration impossible.
    if created and not kwargs.get("raw"):
        OrganizerProfile.objects.get_or_create(user=instance)
