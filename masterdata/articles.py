"""Генерация артикулов, бирок и кодов комплектов (§4.6, МД-17).

Маска собирается из токенов {PREFIX}, {COUNTRY}, {SEQ:n}, {SIZE}, {ARTICLE}.
По умолчанию: модель — {PREFIX}-{SEQ:3} (СВ-117), экземпляр — {ARTICLE}-{SIZE}
(СВ-117-44). Счётчик SEQ ведётся отдельно по каждому префиксу. Счётчики
берутся под блокировкой строки (SELECT … FOR UPDATE), поэтому два продавца
одновременно не получат одинаковый номер.
"""
import re

from django.db import transaction

from .models import Counter

TOKEN_RE = re.compile(r'\{(PREFIX|COUNTRY|SIZE|ARTICLE|SEQ(?::(\d+))?)\}')


def next_seq(org, key: str) -> int:
    with transaction.atomic():
        c, _ = Counter.objects.select_for_update().get_or_create(organization=org, key=key)
        c.value += 1
        c.save(update_fields=['value'])
        return c.value


def bump_counter(org, key: str, value: int):
    """Поднимает счётчик до value (после ручного ввода или импорта СВ-128),
    чтобы следующий автоматический номер не совпал с существующим."""
    with transaction.atomic():
        c, _ = Counter.objects.select_for_update().get_or_create(organization=org, key=key)
        if value > c.value:
            c.value = value
            c.save(update_fields=['value'])


def _render(mask, values, seq=None):
    def repl(m):
        tok = m.group(1)
        if tok.startswith('SEQ'):
            width = int(m.group(2) or 3)
            return str(seq or 0).zfill(width)
        return values.get(tok, '') or ''
    out = TOKEN_RE.sub(repl, mask)
    out = re.sub(r'-{2,}', '-', out).strip('-')
    return out


def _seq_key(prefix, country=''):
    return f'ART:{prefix}:{country}' if country else f'ART:{prefix}'


def generate_model_article(org, category, country=None):
    mask = category.effective_model_mask()
    prefix = category.effective_prefix()
    cc = country.iso_code if (country and '{COUNTRY}' in mask) else ''
    seq = next_seq(org, _seq_key(prefix, cc)) if '{SEQ' in mask else None
    return _render(mask, {'PREFIX': prefix, 'COUNTRY': cc}, seq)


def register_manual_article(org, category, article, country=None):
    """Если артикул введён вручную/импортирован по маске категории —
    поднимаем счётчик префикса до его номера."""
    if not category or not article:
        return
    mask = category.effective_model_mask()
    if '{SEQ' not in mask:
        return
    prefix = category.effective_prefix()
    cc = country.iso_code if (country and '{COUNTRY}' in mask) else ''
    pattern = re.escape(mask)
    pattern = pattern.replace(re.escape('{PREFIX}'), re.escape(prefix))
    pattern = pattern.replace(re.escape('{COUNTRY}'), re.escape(cc))
    pattern = re.sub(r'\\\{SEQ(?::\d+)?\\\}', r'(\\d+)', pattern)
    m = re.fullmatch(pattern, article.strip())
    if m:
        bump_counter(org, _seq_key(prefix, cc), int(m.group(1)))


def item_article(item):
    model = item.model
    if not item.size_id:
        return model.article
    mask = model.category.effective_item_mask()
    return _render(mask, {'ARTICLE': model.article, 'SIZE': item.size.value,
                          'PREFIX': model.category.effective_prefix()})


def new_tag(org) -> str:
    """Бирка: сквозной номер организации, 6 цифр (000123)."""
    return str(next_seq(org, 'TAG')).zfill(6)


def new_kit_code(org) -> str:
    return f'КТ-{str(next_seq(org, "KIT")).zfill(3)}'
