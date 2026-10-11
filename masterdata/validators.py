"""Проверки данных, общие для модуля (МД-20)."""
import re

from django.core.exceptions import ValidationError

_W1 = list(range(1, 12))
_W2 = [3, 4, 5, 6, 7, 8, 9, 10, 11, 1, 2]


def iin_bin_checksum_ok(value: str) -> bool:
    """Контрольная сумма ИИН/БИН Республики Казахстан (12 цифр).
    Алгоритм: сумма произведений первых 11 цифр на веса 1..11 по модулю 11;
    если получилось 10 — повтор с весами 3..11,1,2; если снова 10 — номер
    некорректен. Результат должен совпасть с 12-й цифрой."""
    if not value or not re.fullmatch(r'\d{12}', value):
        return False
    d = [int(c) for c in value]
    c = sum(a * b for a, b in zip(d[:11], _W1)) % 11
    if c == 10:
        c = sum(a * b for a, b in zip(d[:11], _W2)) % 11
        if c == 10:
            return False
    return c == d[11]


def validate_iin_bin(value):
    value = (value or '').strip()
    if not value:
        return
    if not re.fullmatch(r'\d{12}', value):
        raise ValidationError('ИИН/БИН должен состоять из 12 цифр')
    if not iin_bin_checksum_ok(value):
        raise ValidationError('Неверная контрольная сумма ИИН/БИН')


def normalize_phone(value: str) -> str:
    """Приводит казахстанский номер к виду +7XXXXXXXXXX. Иностранные
    номера (не 7/8 и не 10 цифр) оставляет как есть с «+»."""
    raw = (value or '').strip()
    if not raw:
        return ''
    digits = re.sub(r'\D', '', raw)
    if len(digits) == 11 and digits[0] in '78':
        return '+7' + digits[1:]
    if len(digits) == 10:
        return '+7' + digits
    if raw.startswith('+') and 8 <= len(digits) <= 15:
        return '+' + digits
    raise ValidationError('Телефон должен быть в формате +7 XXX XXX XX XX')


def format_phone(value: str) -> str:
    d = re.sub(r'\D', '', value or '')
    if len(d) == 11 and d[0] == '7':
        return f'+7 {d[1:4]} {d[4:7]} {d[7:9]} {d[9:11]}'
    return value or ''


def phone_digits(value: str) -> str:
    return re.sub(r'\D', '', value or '')


def mask_tail(value: str, keep: int = 4) -> str:
    """Маскирование в списках: видны только последние 4 цифры (ТЗ §8)."""
    v = value or ''
    if not v:
        return ''
    return '•' * max(0, len(v) - keep) + v[-keep:]


HEX_RE = re.compile(r'^#[0-9A-Fa-f]{6}$')


def validate_hex(value):
    if value and not HEX_RE.match(value):
        raise ValidationError('Цвет в формате #RRGGBB')
