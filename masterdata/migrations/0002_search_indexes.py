"""Триграммный поиск (pg_trgm, §8): GIN-индексы по артикулу, бирке,
наименованию, ФИО и телефону — поиск по подстроке до 300 мс.
На не-PostgreSQL базах (например, SQLite при сборке) миграция ничего не делает."""
from django.db import migrations

INDEXES = [
    ('md_product_model', 'article'), ('md_product_model', 'name'),
    ('md_item', 'tag'), ('md_item', 'barcode'),
    ('md_client', 'full_name'), ('md_client', 'phone_digits'),
    ('md_counterparty', 'name'),
]


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    schema_editor.execute('CREATE EXTENSION IF NOT EXISTS pg_trgm')
    for table, col in INDEXES:
        schema_editor.execute(
            f'CREATE INDEX IF NOT EXISTS {table}_{col}_trgm ON {table} USING gin (UPPER({col}) gin_trgm_ops)')


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    for table, col in INDEXES:
        schema_editor.execute(f'DROP INDEX IF EXISTS {table}_{col}_trgm')


class Migration(migrations.Migration):
    dependencies = [('masterdata', '0001_initial')]
    operations = [migrations.RunPython(forwards, backwards)]
