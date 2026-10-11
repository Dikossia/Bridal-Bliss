"""История изменений (МД-22) и журнал структуры (МД-12)."""
import datetime as dt
from decimal import Decimal

from . import fieldtypes
from . import models as m
from .refs import LabelCache
from .validators import mask_tail

MASKED = {'iin', 'doc_number'}


def _fmt(v):
    if v is None or v == '':
        return ''
    if isinstance(v, bool):
        return 'да' if v else 'нет'
    if isinstance(v, Decimal):
        return format(v.normalize(), 'f') if v == v.to_integral_value() else str(v)
    if isinstance(v, dt.datetime):
        return v.strftime('%d.%m.%Y %H:%M')
    if isinstance(v, dt.date):
        return v.strftime('%d.%m.%Y')
    return str(v)


def snapshot(obj, field_defs):
    """{код поля: читаемое значение} — по описаниям полей справочника."""
    org = obj.organization
    labels = LabelCache(org)
    out = {}
    is_record = isinstance(obj, m.DirectoryRecord)
    for fd in field_defs:
        if fd.type == 'computed' and fd.code != 'components':
            continue
        if is_record or not fd.is_system:
            src = obj.data if is_record else (obj.extra or {})
            out[fd.code] = fieldtypes.display_json_value(fd, src.get(fd.code), labels)
            continue
        if fd.code == 'components' and isinstance(obj, m.Kit):
            out[fd.code] = '; '.join(f'{c.item.tag} ({c.get_role_display()})'
                                     for c in obj.components.select_related('item').all())
            continue
        try:
            val = getattr(obj, fd.code)
        except Exception:
            continue
        if hasattr(val, 'all'):
            out[fd.code] = '; '.join(sorted(str(x) for x in val.all()))
        elif hasattr(val, 'pk'):
            out[fd.code] = str(val)
        elif fd.type == 'choice':
            if isinstance(val, list):
                opts = {o['value']: o['label'] for o in fd.options}
                out[fd.code] = '; '.join(opts.get(x, x) for x in val)
            else:
                out[fd.code] = dict((o['value'], o['label']) for o in fd.options).get(val, _fmt(val))
        elif isinstance(val, list):
            out[fd.code] = '; '.join(map(str, val))
        else:
            out[fd.code] = mask_tail(_fmt(val)) if fd.code in MASKED else _fmt(val)
    if is_record:
        out['parent'] = str(obj.parent) if obj.parent_id else ''
    if hasattr(obj, 'code') and not any(f.code == 'code' for f in field_defs):
        out['code'] = obj.code or ''
    return out


def diff(old, new, field_defs):
    labels = {f.code: f.name for f in field_defs}
    labels.setdefault('code', 'Код')
    labels.setdefault('parent', 'Родитель')
    changes = []
    for k in new.keys() | old.keys():
        a, b = old.get(k, ''), new.get(k, '')
        if a != b:
            changes.append({'field': k, 'label': labels.get(k, k), 'old': a, 'new': b})
    order = {f.code: i for i, f in enumerate(field_defs)}
    changes.sort(key=lambda c: order.get(c['field'], 999))
    return changes


def log(obj, entity, action, user, changes=None, source='ui'):
    return m.AuditLog.objects.create(
        organization=obj.organization, entity=entity, record_id=str(obj.pk), record_repr=str(obj)[:255],
        action=action, user=user, changes=changes or [], source=source,
        record_owner_id=getattr(obj, 'created_by_id', None))


def structure_log(org, code, action, user, **details):
    return m.StructureLog.objects.create(organization=org, directory_code=code, action=action, user=user,
                                         details=details)
