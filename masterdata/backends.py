"""
Движок справочников: единый интерфейс для системных (Django-модели) и
пользовательских (DirectoryRecord) справочников. Им пользуются API,
импорт и экспорт — поэтому поиск, фильтры, правила и журнал везде одни.
"""
import re
import uuid

from django.db import IntegrityError, transaction
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone
from rest_framework import exceptions, serializers

from . import audit, fieldtypes
from . import models as m
from .api.serializers import make_serializer
from .refs import LabelCache, find_references, resolve_ref
from .registry import REGISTRY


def _vals(raw):
    return [v for v in str(raw).split(',') if v != '']


def _uuid_vals(raw):
    out = []
    for v in _vals(raw):
        try:
            out.append(str(uuid.UUID(v)))
        except ValueError:
            pass
    return out


def _bool(raw):
    return str(raw).lower() in ('1', 'true', 'yes', 'да')


class BaseBackend:
    hierarchical = False
    supports_photo = False

    def __init__(self, org, user=None, policy=None, directory=None):
        self.org, self.user, self.policy = org, user, policy
        self.directory = directory
        self.pk_cache = {}  # кэш связанных объектов на время массовой операции

    # ---------- описание полей ----------
    def all_fields(self, include_archived=False):
        if not hasattr(self, '_fields'):
            self._fields = list(m.DirectoryField.objects.filter(directory=self.directory).order_by('order', 'created_at'))
        return [f for f in self._fields if include_archived or not f.is_archived]

    def field(self, code):
        for f in self.all_fields():
            if f.code == code:
                return f
        return None

    def visible_fields(self):
        hidden = self.policy.hidden if self.policy else set()
        return [f for f in self.all_fields() if f.code not in hidden]

    # ---------- журнал ----------
    def _snapshot(self, obj):
        return audit.snapshot(obj, self.all_fields())


# ============================================================
# Системные справочники
# ============================================================
class SystemBackend(BaseBackend):
    def __init__(self, org, user=None, policy=None, directory=None, spec=None):
        super().__init__(org, user, policy, directory)
        self.spec = spec
        self.code = spec.code
        self.model = spec.model
        self.hierarchical = spec.hierarchical
        self.supports_photo = spec.supports_photo

    @property
    def json_prefix(self):
        return 'extra'

    def base_qs(self):
        qs = self.model.objects.filter(organization=self.org)
        if self.spec.select_related:
            qs = qs.select_related(*self.spec.select_related)
        if self.spec.prefetch:
            qs = qs.prefetch_related(*self.spec.prefetch)
        return qs

    def get(self, pk):
        try:
            return self.base_qs().get(pk=pk)
        except (self.model.DoesNotExist, ValueError, Exception):
            raise exceptions.NotFound('Запись не найдена')

    def serializer(self, instance=None, data=None, mode='detail', partial=False, source='ui',
                   create_missing=False):
        cls = make_serializer(self.spec)
        ctx = {'org': self.org, 'user': self.user, 'policy': self.policy, 'fields': self.all_fields(),
               'mode': mode, 'source': source, 'create_missing': create_missing,
               'pk_cache': self.pk_cache if source == 'import' else None}
        if data is None:
            return cls(instance, context=ctx)
        return cls(instance, data=data, partial=partial, context=ctx)

    def represent(self, obj, mode='detail'):
        return self.serializer(obj, mode=mode).data

    def represent_many(self, objs, mode='list'):
        cls = make_serializer(self.spec)
        ctx = {'org': self.org, 'user': self.user, 'policy': self.policy, 'fields': self.all_fields(),
               'mode': mode}
        return cls(objs, many=True, context=ctx).data

    def save(self, data, instance=None, partial=False, source='ui', create_missing=False):
        before = self._snapshot(instance) if instance is not None else None
        ser = self.serializer(instance, data=data, partial=partial, source=source, create_missing=create_missing)
        ser.is_valid(raise_exception=True)
        with transaction.atomic():
            obj = ser.save()
            if source != 'import':
                obj = self.base_qs().get(pk=obj.pk)
            after = self._snapshot(obj)
            if instance is None:
                changes = [c for c in audit.diff({}, after, self.all_fields()) if c['new'] != '']
                audit.log(obj, self.code, 'create', self.user, changes, source)
            else:
                changes = audit.diff(before, after, self.all_fields())
                if changes:
                    audit.log(obj, self.code, 'update', self.user, changes, source)
        return obj, ser.warnings

    # ---------- поиск/фильтры ----------
    def search_q(self, q):
        q = (q or '').strip()
        if not q:
            return None
        cond = Q()
        for f in self.spec.search:
            cond |= Q(**{f'{f}__icontains': q})
        for fd in self.all_fields():
            if not fd.is_system and fd.searchable:
                cond |= Q(**{f'extra__{fd.code}__icontains': q})
        if self.code == 'clients':
            digits = re.sub(r'\D', '', q)
            if len(digits) >= 4 and len(digits) == len(re.sub(r'[\s+()\-]', '', q)):
                cond |= Q(phone_digits__contains=digits)
            if re.fullmatch(r'\d{12}', digits):
                from .crypto import blind_hash
                cond |= Q(iin_hash=blind_hash(digits))
        if self.code == 'items':
            mt = re.match(r'^(.+)-([^-]+)$', q)
            if mt:
                cond |= Q(model__article__iexact=mt.group(1), size__value__iexact=mt.group(2))
        if self.code == 'counterparties':
            cond |= Q(bin_iin=q)
        return cond

    def apply_filters(self, qs, params):
        archived = params.get('archived', '')
        if archived in ('only',):
            qs = qs.filter(is_active=False)
        elif not _bool(archived):
            qs = qs.filter(is_active=True)
        sq = self.search_q(params.get('q'))
        if sq is not None:
            qs = qs.filter(sq)
        distinct = False
        for fd in self.all_fields():
            key = fd.code
            if fd.is_system:
                qs, d = self._filter_column(qs, fd, params)
            else:
                qs, d = _filter_json(qs, 'extra', fd, params)
            distinct = distinct or d
        qs, d = self._filter_special(qs, params)
        if self.hierarchical and params.get('parent'):
            p = params['parent']
            qs = qs.filter(parent__isnull=True) if p == 'root' else qs.filter(parent_id__in=_uuid_vals(p))
        if params.get('ids'):
            qs = qs.filter(pk__in=_uuid_vals(params['ids']))
        if distinct or d:
            qs = qs.distinct()
        return qs

    def _filter_column(self, qs, fd, params):
        key = fd.code
        t = fd.type
        if t in ('money', 'integer', 'decimal', 'percent'):
            if params.get(f'{key}__min') not in (None, ''):
                qs = qs.filter(**{f'{key}__gte': fieldtypes.to_decimal(params[f'{key}__min'])})
            if params.get(f'{key}__max') not in (None, ''):
                qs = qs.filter(**{f'{key}__lte': fieldtypes.to_decimal(params[f'{key}__max'])})
            return qs, False
        raw = params.get(key)
        if raw in (None, ''):
            return qs, False
        if t == 'ref':
            ids = _uuid_vals(raw)
            if fd.multiple:
                return qs.filter(**{f'{key}__in': ids}), True
            if fd.ref_directory == 'categories':
                ids = _category_subtrees(self.org, ids)
            return qs.filter(**{f'{key}_id__in': ids}), False
        if t == 'choice':
            vals = _vals(raw)
            if fd.multiple:
                cond = Q()
                for v in vals:
                    cond |= Q(**{f'{key}__contains': [v]})
                return qs.filter(cond), False
            return qs.filter(**{f'{key}__in': vals}), False
        if t == 'bool':
            return qs.filter(**{key: _bool(raw)}), False
        if t in ('date',):
            return qs.filter(**{key: fieldtypes.to_date(raw)}), False
        if t == 'computed':
            return qs, False
        return qs.filter(**{f'{key}__icontains': raw}), False

    def _filter_special(self, qs, params):
        """Фильтры товара (МД-14) через связанные модели."""
        d = False
        if self.code == 'models':
            item_filters = {}
            for key, lookup in (('size', 'size_id__in'), ('salon', 'salon_id__in'), ('stage', 'stage_id__in')):
                if params.get(key):
                    item_filters[lookup] = _uuid_vals(params[key])
            if params.get('status'):
                item_filters['status__in'] = _vals(params['status'])
            if item_filters:
                sub = m.Item.objects.filter(model=OuterRef('pk'), is_active=True, **item_filters)
                qs = qs.filter(Exists(sub))
            if params.get('has_photo') not in (None, ''):
                ph = Exists(m.Photo.objects.filter(product_model=OuterRef('pk')))
                qs = qs.filter(ph) if _bool(params['has_photo']) else qs.exclude(ph)
        if self.code == 'items':
            if params.get('category'):
                qs = qs.filter(model__category_id__in=_category_subtrees(self.org, _uuid_vals(params['category'])))
            if params.get('events'):
                qs, d = qs.filter(model__events__in=_uuid_vals(params['events'])), True
            if params.get('styles'):
                qs, d = qs.filter(model__styles__in=_uuid_vals(params['styles'])), True
            if params.get('operations'):
                qs = qs.filter(model__operations__in=_vals(params['operations']))
            if params.get('rent_price__min'):
                qs = qs.filter(model__rent_price__gte=fieldtypes.to_decimal(params['rent_price__min']))
            if params.get('rent_price__max'):
                qs = qs.filter(model__rent_price__lte=fieldtypes.to_decimal(params['rent_price__max']))
            if params.get('available') not in (None, ''):
                qs = qs.filter(stage__is_available=_bool(params['available']))
            if params.get('has_photo') not in (None, ''):
                ph = Exists(m.Photo.objects.filter(item=OuterRef('pk'))) | \
                    Exists(m.Photo.objects.filter(product_model=OuterRef('model_id')))
                qs = qs.filter(ph) if _bool(params['has_photo']) else qs.exclude(ph)
            if params.get('free'):  # не входит в активный комплект
                qs = qs.exclude(Exists(m.KitItem.objects.filter(item=OuterRef('pk'), kit_active=True)))
        if self.code == 'kits':
            if params.get('model'):
                qs, d = qs.filter(components__item__model_id__in=_uuid_vals(params['model'])), True
            if params.get('item'):
                qs, d = qs.filter(components__item_id__in=_uuid_vals(params['item'])), True
        return qs, d

    def ordering_fields(self):
        concrete = {f.name: f for f in self.model._meta.concrete_fields}
        out = {'created_at': 'created_at', 'updated_at': 'updated_at'}
        for fd in self.all_fields():
            f = concrete.get(fd.code)
            if not f:
                continue
            if f.is_relation:
                rel = f.related_model
                names = {x.name for x in rel._meta.concrete_fields}
                for cand in ('article', 'tag', 'name', 'full_name', 'value'):
                    if cand in names:
                        out[fd.code] = f'{fd.code}__{cand}'
                        break
            else:
                out[fd.code] = fd.code
        if self.code == 'items':
            out['article'] = 'model__article'
        return out

    def apply_ordering(self, qs, ordering):
        allowed = self.ordering_fields()
        keys = []
        for part in _vals(ordering or ''):
            desc = part.startswith('-')
            f = allowed.get(part.lstrip('-'))
            if f:
                keys.append(('-' if desc else '') + f)
        if keys:
            return qs.order_by(*keys, 'pk')
        return qs.order_by(*(self.spec.ordering or ['pk']))

    # ---------- выбор в выпадающих списках ----------
    def options(self, params):
        qs = self.base_qs().filter(is_active=True)
        sq = self.search_q(params.get('q'))
        if sq is not None:
            qs = qs.filter(sq)
        if params.get('ids'):
            qs = self.base_qs().filter(pk__in=_uuid_vals(params['ids']))
        if self.code == 'items':
            if params.get('category'):
                qs = qs.filter(model__category_id__in=_category_subtrees(self.org, _uuid_vals(params['category'])))
            if params.get('model'):
                qs = qs.filter(model_id__in=_uuid_vals(params['model']))
            if _bool(params.get('free', '')):
                busy = m.KitItem.objects.filter(item=OuterRef('pk'), kit_active=True)
                if params.get('kit'):
                    busy = busy.exclude(kit_id__in=_uuid_vals(params['kit']))
                qs = qs.exclude(Exists(busy)).filter(status='active')
        items = list(qs.order_by(*(self.spec.ordering or ['pk']))[:int(params.get('limit') or 50)]) \
            if self.code != 'categories' else list(qs)
        res = []
        if self.code == 'categories':
            leaf_only = _bool(params.get('leaf', ''))
            for c in sorted(items, key=lambda c: (c.path_name())):
                if not params.get('ids') and not c.is_selectable(self.org):
                    continue
                leaf = c.is_leaf()
                if leaf_only and not leaf:
                    continue
                res.append({'id': str(c.pk), 'label': c.path_name(), 'leaf': leaf, 'depth': c.depth,
                            'operations': c.effective_operations(), 'size_required': c.effective_size_required(),
                            'prefix': c.effective_prefix()})
            return res
        if self.code == 'styles' and params.get('category'):
            try:
                cat = m.Category.objects.get(organization=self.org, pk=params['category'])
                items = [s for s in items if s.applicable_to(cat)]
            except (m.Category.DoesNotExist, ValueError, Exception):
                pass
        if self.code == 'styles' and not params.get('ids'):
            # выключенный раздел скрывает и связанные виды (МД-6)
            visible = []
            for s in items:
                cats = list(s.categories.all())
                if not cats or any(c.is_selectable(self.org) for c in cats):
                    visible.append(s)
            items = visible
        for o in items:
            d = {'id': str(o.pk), 'label': str(o)}
            if self.code == 'items':
                d['label'] = f'{o.tag} · {o.article} · {o.model.name}'
                d['category'] = str(o.model.category_id)
                d['section'] = o.model.category.effective_section()
                d['free'] = not o.kit_links.filter(kit_active=True).exists()
            if self.code == 'models':
                d['acquisition'] = o.acquisition
                d['size_required'] = o.category.effective_size_required()
            if self.code == 'manufacturers':
                d['country'] = str(o.country_id) if o.country_id else None
            if self.code == 'colors':
                d['hex'] = o.hex
            res.append(d)
        return res

    # ---------- архив / удаление (МД-21) ----------
    def archive(self, obj, source='ui'):
        if not obj.is_active:
            return obj
        obj.is_active = False
        obj.updated_by = self.user
        obj.save()
        audit.log(obj, self.code, 'archive', self.user, [{'field': 'is_active', 'label': 'Архив',
                                                          'old': 'нет', 'new': 'да'}], source)
        return obj

    def restore(self, obj, source='ui'):
        if obj.is_active:
            return obj
        if isinstance(obj, m.Kit):
            busy = m.KitItem.objects.filter(item__in=obj.components.values('item'), kit_active=True).exclude(kit=obj)
            if busy.exists():
                raise serializers.ValidationError(
                    {'components': ['Часть экземпляров уже входит в другой активный комплект']})
        obj.is_active = True
        obj.updated_by = self.user
        try:
            obj.save()
        except IntegrityError:
            raise serializers.ValidationError('Восстановление нарушает уникальность')
        audit.log(obj, self.code, 'restore', self.user, [{'field': 'is_active', 'label': 'Архив',
                                                          'old': 'да', 'new': 'нет'}], source)
        return obj

    def delete(self, obj):
        """Физически удаляется только запись без ссылок; иначе — архив."""
        refs = find_references(obj)
        if refs:
            self.archive(obj)
            return 'archived', refs
        audit.log(obj, self.code, 'delete', self.user, [])
        try:
            with transaction.atomic():
                if isinstance(obj, (m.ProductModel, m.Item)):
                    from .photos import delete_photo
                    for p in list(obj.photos.all()):
                        delete_photo(p)
                obj.delete()
        except Exception:
            self.archive(obj)
            return 'archived', ['связанные записи']
        return 'deleted', []


def _category_subtrees(org, ids):
    out = set(ids)
    frontier = list(ids)
    while frontier:
        frontier = [str(x) for x in m.Category.objects.filter(organization=org, parent_id__in=frontier)
                    .values_list('id', flat=True)]
        out.update(frontier)
    return list(out)


def _filter_json(qs, prefix, fd, params):
    key, t = fd.code, fd.type
    path = f'{prefix}__{key}'
    if t in ('money', 'integer', 'decimal', 'percent'):
        if params.get(f'{key}__min') not in (None, ''):
            qs = qs.filter(**{f'{path}__gte': float(fieldtypes.to_decimal(params[f'{key}__min']))})
        if params.get(f'{key}__max') not in (None, ''):
            qs = qs.filter(**{f'{path}__lte': float(fieldtypes.to_decimal(params[f'{key}__max']))})
        return qs, False
    raw = params.get(key)
    if raw in (None, ''):
        return qs, False
    if t in ('ref', 'choice'):
        vals = _vals(raw)
        if fd.multiple:
            cond = Q()
            for v in vals:
                cond |= Q(**{f'{path}__contains': [v]})
            return qs.filter(cond), False
        return qs.filter(**{f'{path}__in': vals}), False
    if t == 'bool':
        return qs.filter(**{path: _bool(raw)}), False
    return qs.filter(**{f'{path}__icontains': raw}), False


# ============================================================
# Пользовательские справочники
# ============================================================
class CustomBackend(BaseBackend):
    def __init__(self, org, user=None, policy=None, directory=None):
        super().__init__(org, user, policy, directory)
        self.code = directory.code
        self.hierarchical = directory.is_hierarchical
        self.supports_photo = directory.supports_photo

    @property
    def json_prefix(self):
        return 'data'

    def base_qs(self):
        return m.DirectoryRecord.objects.filter(organization=self.org, directory=self.directory) \
            .select_related('parent', 'directory')

    def get(self, pk):
        try:
            return self.base_qs().get(pk=pk)
        except Exception:
            raise exceptions.NotFound('Запись не найдена')

    def _resolver(self, create_missing=False):
        return lambda code, raw: resolve_ref(self.org, code, raw, create_missing, self.user)

    def validate(self, data, instance=None, partial=False, create_missing=False):
        errors, values = {}, dict(instance.data) if instance else {}
        p = self.policy
        for fd in self.all_fields():
            if fd.type == 'computed':
                continue
            if fd.code in data:
                if p is not None and fd.code in p.hidden:
                    continue
                if p is not None and fd.code in p.readonly and instance is not None and \
                        data[fd.code] != values.get(fd.code):
                    errors[fd.code] = ['Нет прав на изменение поля']
                    continue
                try:
                    values[fd.code] = fieldtypes.coerce_json_value(fd, data[fd.code],
                                                                   resolve_ref=self._resolver(create_missing))
                except Exception as e:
                    errors[fd.code] = list(getattr(e, 'messages', [str(e)]))
                    continue
            elif instance is None and fd.default not in (None, ''):
                values[fd.code] = fd.default
            v = values.get(fd.code)
            if fd.required and fieldtypes.is_empty(v) and not (partial and fd.code not in data and instance):
                errors[fd.code] = ['Обязательное поле']
            elif fd.unique and not fieldtypes.is_empty(v):
                qs = self.base_qs().filter(**{f'data__{fd.code}': v})
                if instance is not None:
                    qs = qs.exclude(pk=instance.pk)
                if qs.exists():
                    errors[fd.code] = ['Значение должно быть уникальным']
        extra = {}
        if 'code' in data:
            code = (data.get('code') or '').strip()
            if code:
                qs = self.base_qs().filter(code=code)
                if instance is not None:
                    qs = qs.exclude(pk=instance.pk)
                if qs.exists():
                    errors['code'] = ['Код уже используется']
            extra['code'] = code
        if self.hierarchical and 'parent' in data:
            pid = data.get('parent') or None
            parent = None
            if pid:
                try:
                    parent = self.base_qs().get(pk=resolve_ref(self.org, self.code, pid))
                except Exception:
                    errors['parent'] = ['Родитель не найден']
                node, guard = parent, 0
                while node is not None and guard < 20:
                    if instance is not None and node.pk == instance.pk:
                        errors['parent'] = ['Запись не может быть вложена сама в себя']
                        break
                    node, guard = node.parent, guard + 1
            extra['parent'] = parent
        if errors:
            raise serializers.ValidationError(errors)
        return values, extra

    def save(self, data, instance=None, partial=False, source='ui', create_missing=False):
        before = self._snapshot(instance) if instance is not None else None
        values, extra = self.validate(data, instance, partial, create_missing)
        with transaction.atomic():
            if instance is None:
                obj = m.DirectoryRecord(organization=self.org, directory=self.directory, created_by=self.user)
            else:
                obj = instance
            obj.data = values
            obj.updated_by = self.user
            if 'code' in extra:
                obj.code = extra['code']
            if 'parent' in extra:
                obj.parent = extra['parent']
            obj.save()
            after = self._snapshot(obj)
            if instance is None:
                audit.log(obj, self.code, 'create', self.user,
                          [c for c in audit.diff({}, after, self.all_fields()) if c['new'] != ''], source)
            else:
                ch = audit.diff(before, after, self.all_fields())
                if ch:
                    audit.log(obj, self.code, 'update', self.user, ch, source)
        return obj, []

    def represent(self, obj, mode='detail', labels=None):
        labels = labels or LabelCache(self.org)
        hidden = self.policy.hidden if self.policy else set()
        d = {'id': str(obj.pk), 'code': obj.code, 'is_active': obj.is_active,
             'created_at': obj.created_at, 'updated_at': obj.updated_at,
             'parent': str(obj.parent_id) if obj.parent_id else None,
             'parent__display': str(obj.parent) if obj.parent_id else '', '_title': str(obj)}
        for fd in self.all_fields():
            if fd.code in hidden:
                continue
            v = obj.data.get(fd.code)
            d[fd.code] = v
            if fd.type in ('ref', 'choice'):
                d[f'{fd.code}__display'] = fieldtypes.display_json_value(fd, v, labels)
        if self.supports_photo:
            from .api.serializers import photo_urls
            ph = obj.photos.order_by('-is_main', 'order').first()
            d['main_photo'] = photo_urls(ph) if ph else None
        if mode == 'detail':
            d['created_by__display'] = getattr(obj.created_by, 'name', '') if obj.created_by_id else ''
            d['updated_by__display'] = getattr(obj.updated_by, 'name', '') if obj.updated_by_id else ''
        return d

    def represent_many(self, objs, mode='list'):
        labels = LabelCache(self.org)
        return [self.represent(o, mode, labels) for o in objs]

    def search_q(self, q):
        q = (q or '').strip()
        if not q:
            return None
        cond = Q(code__icontains=q)
        df = self.directory.display_field or 'name'
        cond |= Q(**{f'data__{df}__icontains': q})
        for fd in self.all_fields():
            if fd.searchable:
                cond |= Q(**{f'data__{fd.code}__icontains': q})
        return cond

    def apply_filters(self, qs, params):
        archived = params.get('archived', '')
        if archived == 'only':
            qs = qs.filter(is_active=False)
        elif not _bool(archived):
            qs = qs.filter(is_active=True)
        sq = self.search_q(params.get('q'))
        if sq is not None:
            qs = qs.filter(sq)
        for fd in self.all_fields():
            qs, _ = _filter_json(qs, 'data', fd, params)
        if self.hierarchical and params.get('parent'):
            p = params['parent']
            qs = qs.filter(parent__isnull=True) if p == 'root' else qs.filter(parent_id__in=_uuid_vals(p))
        if params.get('ids'):
            qs = qs.filter(pk__in=_uuid_vals(params['ids']))
        if self.supports_photo and params.get('has_photo') not in (None, ''):
            ph = Exists(m.Photo.objects.filter(record=OuterRef('pk')))
            qs = qs.filter(ph) if _bool(params['has_photo']) else qs.exclude(ph)
        return qs

    def apply_ordering(self, qs, ordering):
        keys = []
        codes = {f.code for f in self.all_fields()}
        for part in _vals(ordering or ''):
            desc = part.startswith('-')
            f = part.lstrip('-')
            if f in codes:
                keys.append(('-' if desc else '') + f'data__{f}')
            elif f in ('created_at', 'updated_at', 'code'):
                keys.append(part)
        df = self.directory.display_field or 'name'
        return qs.order_by(*(keys or [f'data__{df}', 'created_at']), 'pk')

    def options(self, params):
        qs = self.base_qs().filter(is_active=True)
        sq = self.search_q(params.get('q'))
        if sq is not None:
            qs = qs.filter(sq)
        if params.get('ids'):
            qs = self.base_qs().filter(pk__in=_uuid_vals(params['ids']))
        return [{'id': str(o.pk), 'label': str(o)} for o in self.apply_ordering(qs, '')[:int(params.get('limit') or 50)]]

    def archive(self, obj, source='ui'):
        if obj.is_active:
            obj.is_active, obj.updated_by = False, self.user
            obj.save()
            audit.log(obj, self.code, 'archive', self.user, [], source)
        return obj

    def restore(self, obj, source='ui'):
        if not obj.is_active:
            obj.is_active, obj.updated_by = True, self.user
            obj.save()
            audit.log(obj, self.code, 'restore', self.user, [], source)
        return obj

    def delete(self, obj):
        refs = find_references(obj)
        if refs:
            self.archive(obj)
            return 'archived', refs
        audit.log(obj, self.code, 'delete', self.user, [])
        obj.delete()
        return 'deleted', []


def get_backend(org, code, user=None, policy=None):
    directory = m.Directory.objects.filter(organization=org, code=code).first()
    spec = REGISTRY.get(code)
    if spec is not None:
        if directory is None:
            from .seed import sync_system_directories
            sync_system_directories(org)
            directory = m.Directory.objects.get(organization=org, code=code)
        return SystemBackend(org, user, policy, directory, spec)
    if directory is None:
        raise exceptions.NotFound('Справочник не найден')
    return CustomBackend(org, user, policy, directory)
