"""МД-4: системные справочники создаются миграцией при развёртывании —
для уже существующих организаций (новые получают их при регистрации)."""
from django.db import migrations


def forwards(apps, schema_editor):
    from accounts.models import Organization
    from masterdata.seed import seed_organization
    for org in Organization.objects.all():
        seed_organization(org)


class Migration(migrations.Migration):
    dependencies = [('masterdata', '0002_search_indexes'), ('accounts', '0003_organizations')]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
