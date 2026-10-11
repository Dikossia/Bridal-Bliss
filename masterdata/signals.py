"""При регистрации новой организации создаются все системные справочники
с начальным наполнением (МД-4)."""
from django.db.models.signals import post_save
from django.dispatch import receiver

from accounts.models import Organization


@receiver(post_save, sender=Organization)
def seed_new_organization(sender, instance, created, raw=False, **kwargs):
    if created and not raw:
        from .seed import seed_organization
        seed_organization(instance)
