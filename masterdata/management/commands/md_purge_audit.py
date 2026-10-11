from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from masterdata.models import AuditLog


class Command(BaseCommand):
    help = 'Удалить записи истории старше N лет (по умолчанию 3 — минимальный срок хранения по ТЗ §8)'

    def add_arguments(self, parser):
        parser.add_argument('--years', type=int, default=3)

    def handle(self, years, **opts):
        years = max(3, years)
        cut = timezone.now() - timedelta(days=365 * years + 1)
        n, _ = AuditLog.objects.filter(at__lt=cut).delete()
        self.stdout.write(f'Удалено записей истории: {n}')
