"""Ссылки между справочниками: поиск значения по коду/названию (МД-29),
подписи для отображения и проверка «есть ли на запись ссылки» (МД-5, МД-21)."""
import uuid

from django.core.exceptions import ValidationError
from django.db.models import Q

from . import models as m
from .registry import REGISTRY

# По каким полям ищется значение ссылки при импорте (кроме id и code)
LOOKUP_FIELDS = {
    'models': ['article', 'name'],
    'items': ['tag', 'barcode'],
    'sizes': ['value'],
    'countries': ['iso_code', 'name'],
    'clients': ['full_name', 'phone'],
    'counterparties': ['name', 'bin_iin'],
    'kits': ['name'],
}


def _is_uuid(s):
    try:
        uuid.UUID(str(s))
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def ref_queryset(org, code):
    spec = REGISTRY.get(code)
    if spec:
        return spec.model.objects.filter(organization=org)
    return m.DirectoryRecord.objects.filter(organization=org, directory__code=code)


def _custom_display_field(org, code):
    d = m.Directory.objects.filter(organization=org, code=code).first()
    return (d.display_field or 'name') if d else 'name'


def find_ref(org, code, raw):
    """Находит запись по id, коду или названию без учёта регистра."""
    qs = ref_queryset(org, code)
    s = str(raw).strip()
    if not s:
        return None
    if _is_uuid(s):
        obj = qs.filter(pk=s).first()
        if obj:
            return obj
    spec = REGISTRY.get(code)
    if spec:
        fields = ['code'] + LOOKUP_FIELDS.get(code, [spec.display_field])
        if code == 'sizes':
            # «44» или «44 EU»
            parts = s.split()
            if len(parts) == 2:
                obj = qs.filter(value__iexact=parts[0], system__iexact=parts[1]).first()
                if obj:
                    return obj
            obj = qs.filter(value__iexact=s).order_by('system').first()
            if obj:
                return obj
        cond = Q()
        for f in dict.fromkeys(fields):
            cond |= Q(**{f'{f}__iexact': s})
        objs = list(qs.filter(cond).order_by('-is_active')[:2])
        if code == 'categories' and not objs and '/' in s:
            # «Ұзату / Қамзол» — путь в дереве
            leaf = s.split('/')[-1].strip()
            for c in qs.filter(name__iexact=leaf):
                if c.path_name().lower() == ' / '.join(p.strip() for p in s.split('/')).lower():
                    return c
        return objs[0] if objs else None
    df = _custom_display_field(org, code)
    return qs.filter(Q(code__iexact=s) | Q(**{f'data__{df}__iexact': s})).order_by('-is_active').first()


def resolve_ref(org, code, raw, create_missing=False, user=None):
    obj = find_ref(org, code, raw)
    if obj is None and create_missing and not _is_uuid(raw):
        obj = create_missing_ref(org, code, str(raw).strip(), user)
    if obj is None:
        raise ValidationError(f'Не найдено значение «{raw}» в справочнике')
    return str(obj.pk)


# Справочники, недостающие значения которых можно создать при импорте
# (только «простые» — где достаточно названия).
SIMPLE_CREATABLE = {'events', 'styles', 'colors', 'manufacturers', 'photo_types', 'defect_types'}


def create_missing_ref(org, code, name, user=None):
    spec = REGISTRY.get(code)
    if spec:
        if code == 'sizes':
            return m.Size.objects.create(organization=org, value=name, system='RU', created_by=user)
        if code not in SIMPLE_CREATABLE:
            return None
        return spec.model.objects.create(organization=org, name=name, created_by=user)
    d = m.Directory.objects.filter(organization=org, code=code).first()
    if not d:
        return None
    return m.DirectoryRecord.objects.create(organization=org, directory=d,
                                            data={d.display_field or 'name': name}, created_by=user)


class LabelCache:
    def __init__(self, org):
        self.org, self.cache = org, {}

    def __call__(self, code, value):
        key = (code, str(value))
        if key not in self.cache:
            obj = ref_queryset(self.org, code).filter(pk=value).first() if _is_uuid(value) else None
            self.cache[key] = str(obj) if obj else str(value)
        return self.cache[key]


IGNORED_REVERSE = {'photos', 'kit_links'}  # фото — часть самой записи


def find_references(obj, limit=3):
    """Список ссылок на запись (для МД-5/МД-21): [«Модели: СВ-117 …», …]."""
    found = []
    for rel in obj._meta.related_objects:
        accessor = rel.get_accessor_name()
        if not accessor or rel.related_model is m.Photo:
            continue
        if rel.related_model is m.KitItem:
            if obj.kit_links.filter(kit_active=True).exists():
                found.append('Активный комплект')
            continue
        if rel.one_to_one:
            continue
        try:
            manager = getattr(obj, accessor)
        except Exception:
            continue
        qs = manager.all()
        if rel.related_model is m.Kit:
            pass
        if qs.exists():
            vn = rel.related_model._meta.verbose_name_plural
            found.append(f'{vn}: ' + ', '.join(str(x) for x in qs[:limit]))
    # Ссылки из JSON-полей (доп. поля и пользовательские справочники)
    code = getattr(obj, 'DICT', '') or (obj.directory.code if isinstance(obj, m.DirectoryRecord) else '')
    if code:
        sid = str(obj.pk)
        for f in m.DirectoryField.objects.filter(organization=obj.organization, type='ref', ref_directory=code,
                                                 is_system=False).select_related('directory'):
            d = f.directory
            lookup = {f'data__{f.code}__contains': [sid]} if f.multiple else {f'data__{f.code}': sid}
            if d.is_system:
                spec = REGISTRY.get(d.code)
                if not spec:
                    continue
                lookup = {k.replace('data__', 'extra__'): v for k, v in lookup.items()}
                qs = spec.model.objects.filter(organization=obj.organization, **lookup)
            else:
                qs = m.DirectoryRecord.objects.filter(organization=obj.organization, directory=d, **lookup)
            if qs.exists():
                found.append(f'{d.name}: ' + ', '.join(str(x) for x in qs[:limit]))
    return found
