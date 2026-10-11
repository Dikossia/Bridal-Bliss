from django.core.management.base import BaseCommand

from accounts.models import Organization
from masterdata.seed import seed_organization


class Command(BaseCommand):
    help = 'Создать/досоздать системные справочники и начальное наполнение для всех организаций (МД-4)'

    def handle(self, *args, **opts):
        for org in Organization.objects.all():
            seed_organization(org)
            self.stdout.write(f'✓ {org.name}')
