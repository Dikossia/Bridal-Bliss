"""
Типы полей конструктора (МД-8, МД-9) и преобразование значений.

Используется в трёх местах — поэтому правила одинаковы везде:
  • валидация доп. полей системных справочников (extra) и записей
    пользовательских справочников (data);
  • импорт из XLSX/CSV (сырые строки → значения, МД-29);
  • экспорт (значения → читаемый текст).
"""
import datetime as dt
import re
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from .validators import iin_bin_checksum_ok, normalize_phone

TRUE_WORDS = {'1', 'true', 'да', 'yes', 'y', 'иә', '+', 'истина', 'x', 'v', '✓'}
FALSE_WORDS = {'0', 'false', 'нет', 'no', 'n', 'жоқ', '-', 'ложь', ''}

# Безопасные смены типа поля с данными (МД-11)
SAFE_TYPE_CHANGES = {('integer', 'decimal'), ('integer', 'money'), ('decimal', 'money'), ('money', 'decimal'),
                     ('string', 'text'), ('phone', 'string'), ('email', 'string'), ('iin_bin', 'string')}


def is_empty(v):
    return v is None or v == '' or v == [] or (isinstance(v, str) and not v.strip())


def to_bool(raw):
    if isinstance(raw, bool):
        return raw
    s = str(raw).strip().lower()
    if s in TRUE_WORDS:
        return True
    if s in FALSE_WORDS:
        return False
    raise ValidationError('Ожидается «да» или «нет»')


def to_decimal(raw):
    if isinstance(raw, (int, float, Decimal)) and not isinstance(raw, bool):
        return Decimal(str(raw))
    s = str(raw).strip().replace(' ', '').replace(' ', '').replace('₸', '').replace(',', '.')
    if s.endswith('%'):
        s = s[:-1]
    try:
        return Decimal(s)
    except InvalidOperation:
        raise ValidationError('Ожидается число')


def to_int(raw):
    d = to_decimal(raw)
    if d != d.to_integral_value():
        raise ValidationError('Ожидается целое число')
    return int(d)


DATE_FORMATS = ['%Y-%m-%d', '%d.%m.%Y', '%d.%m.%y', '%d/%m/%Y', '%Y.%m.%d']


def to_date(raw):
    if isinstance(raw, dt.datetime):
        return raw.date()
    if isinstance(raw, dt.date):
        return raw
    s = str(raw).strip()[:10] if 'T' in str(raw) else str(raw).strip()
    for fmt in DATE_FORMATS:
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    raise ValidationError('Дата в формате ДД.ММ.ГГГГ')


def to_datetime(raw):
    if isinstance(raw, dt.datetime):
        return raw
    if isinstance(raw, dt.date):
        return dt.datetime.combine(raw, dt.time())
    s = str(raw).strip()
    for fmt in ['%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M',
                '%d.%m.%Y %H:%M', '%d.%m.%Y %H:%M:%S']:
        try:
            return dt.datetime.strptime(s[:19], fmt)
        except ValueError:
            pass
    try:
        return dt.datetime.combine(to_date(s), dt.time())
    except ValidationError:
        raise ValidationError('Дата и время в формате ДД.ММ.ГГГГ ЧЧ:ММ')


def split_multi(raw):
    """Множественные значения разделяются «;» (МД-29)."""
    if isinstance(raw, (list, tuple)):
        return [x for x in raw if not is_empty(x)]
    return [p.strip() for p in str(raw).split(';') if p.strip()]


def match_choice(options, raw):
    s = str(raw).strip().lower()
    for o in options:
        if s == str(o['value']).lower() or s == str(o['label']).lower():
            return o['value']
    raise ValidationError(f'Нет такого значения в списке: «{raw}»')


def _num_json(d: Decimal):
    return int(d) if d == d.to_integral_value() else float(d)


def check_string_rules(value, validation):
    v = validation or {}
    if v.get('min_len') and len(value) < int(v['min_len']):
        raise ValidationError(f'Минимум {v["min_len"]} символов')
    if v.get('max_len') and len(value) > int(v['max_len']):
        raise ValidationError(f'Максимум {v["max_len"]} символов')
    if v.get('mask'):
        try:
            if not re.fullmatch(v['mask'], value):
                raise ValidationError('Значение не соответствует маске')
        except re.error:
            pass


def check_number_rules(value, validation):
    v = validation or {}
    if v.get('min') not in (None, '') and value < Decimal(str(v['min'])):
        raise ValidationError(f'Не меньше {v["min"]}')
    if v.get('max') not in (None, '') and value > Decimal(str(v['max'])):
        raise ValidationError(f'Не больше {v["max"]}')


def coerce_json_value(fdef, raw, *, resolve_ref=None):
    """Сырое значение → JSON-значение для extra/data. resolve_ref(code, raw)
    находит id записи справочника (по id, коду или названию)."""
    t = fdef.type
    if t in ('computed',):
        return None
    if fdef.multiple and t in ('choice', 'ref', 'string'):
        parts = split_multi(raw) if not is_empty(raw) else []
        if t == 'choice':
            return [match_choice(fdef.options, p) for p in parts]
        if t == 'ref':
            return [resolve_ref(fdef.ref_directory, p) for p in parts]
        out = [str(p).strip() for p in parts]
        for p in out:
            check_string_rules(p, fdef.validation)
        return out
    if is_empty(raw):
        return None
    if t in ('string', 'text'):
        s = str(raw).strip() if t == 'string' else str(raw)
        check_string_rules(s, fdef.validation)
        return s
    if t == 'phone':
        return normalize_phone(str(raw))
    if t == 'email':
        s = str(raw).strip()
        try:
            validate_email(s)
        except ValidationError:
            raise ValidationError('Некорректный email')
        return s
    if t == 'iin_bin':
        s = re.sub(r'\s', '', str(raw))
        if isinstance(raw, (int, float)):
            s = str(int(raw)).zfill(12)
        if not re.fullmatch(r'\d{12}', s) or not iin_bin_checksum_ok(s):
            raise ValidationError('Неверный ИИН/БИН (12 цифр, контрольная сумма)')
        return s
    if t == 'integer':
        v = to_int(raw)
        check_number_rules(Decimal(v), fdef.validation)
        return v
    if t in ('decimal', 'money', 'percent'):
        d = to_decimal(raw)
        if t == 'money':
            d = d.quantize(Decimal('0.01'))
        check_number_rules(d, fdef.validation)
        return _num_json(d)
    if t == 'date':
        return to_date(raw).isoformat()
    if t == 'datetime':
        return to_datetime(raw).isoformat(timespec='minutes')
    if t == 'bool':
        return to_bool(raw)
    if t == 'choice':
        return match_choice(fdef.options, raw)
    if t == 'ref':
        return resolve_ref(fdef.ref_directory, raw)
    if t in ('file', 'photo'):
        return raw  # {name, path} / список id фото — пишется своими эндпоинтами
    return raw


def display_json_value(fdef, value, ref_label=None):
    """JSON-значение → текст для экспорта/истории."""
    if is_empty(value):
        return ''
    if isinstance(value, list):
        return '; '.join(display_json_value(_Single(fdef), v, ref_label) for v in value)
    if fdef.type == 'bool':
        return 'да' if value else 'нет'
    if fdef.type == 'choice':
        for o in fdef.options or []:
            if o['value'] == value:
                return o['label']
    if fdef.type == 'ref' and ref_label:
        return ref_label(fdef.ref_directory, value)
    if fdef.type == 'date':
        try:
            return dt.date.fromisoformat(value).strftime('%d.%m.%Y')
        except (TypeError, ValueError):
            pass
    if isinstance(value, dict):
        return value.get('name') or ''
    return str(value)


class _Single:
    def __init__(self, f):
        self.__dict__.update({k: getattr(f, k) for k in ('type', 'options', 'ref_directory', 'validation')})
        self.multiple = False
