from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import Membership, Organization, User


class Command(BaseCommand):
    help = 'Создать организацию и назначить владельца: md_create_org "Bridal Bliss" owner@mail.kz'

    def add_arguments(self, parser):
        parser.add_argument('name')
        parser.add_argument('owner_email')
        parser.add_argument('--role', default='owner', choices=[r for r, _ in Membership.ROLE_CHOICES])

    @transaction.atomic
    def handle(self, name, owner_email, role, **opts):
        user = User.objects.filter(email=owner_email.strip().lower()).first()
        if user is None:
            raise CommandError('Пользователь не найден — сначала зарегистрируйтесь (/register) или createsuperuser')
        org = Organization.objects.filter(name=name).first()
        created = org is None
        if created:
            org = Organization.objects.create(name=name)  # справочники создаются сигналом
        Membership.objects.update_or_create(user=user, organization=org, defaults={'role': role, 'is_active': True})
        self.stdout.write(f'{"Создана" if created else "Найдена"} организация «{org.name}» ({org.pk}); '
                          f'{user.email} — {role}')
