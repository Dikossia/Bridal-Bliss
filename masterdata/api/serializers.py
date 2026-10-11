"""
Сериализаторы системных справочников + бизнес-правила (МД-20, §4.3–4.7).

Все справочники строятся одной фабрикой make_serializer(spec) поверх
ModelSerializer. Общая часть (BaseMDSerializer):
  • связи ограничены организацией (чужие id = «не найдено»);
  • доп. поля из «Структуры» (extra) выводятся и принимаются на верхнем
    уровне, как обычные поля, и проверяются по описанию поля (МД-10);
  • права на уровне полей: скрытые поля роли не выводятся и не
    принимаются; read-only поля нельзя изменить (§6);
  • в ответе — подписи ссылок и списков (<поле>__display).
Специфика справочников — в миксинах ниже.
"""
from decimal import Decimal

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers

from .. import articles, fieldtypes
from .. import models as m
from ..refs import LabelCache, resolve_ref
from ..validators import format_phone, iin_bin_checksum_ok, mask_tail, normalize_phone, validate_hex

BASE_OUT = ['id', 'is_active', 'created_at', 'updated_at']
ERR_RIGHTS = 'Нет прав на изменение поля'


def _err(field, msg):
    raise serializers.ValidationError({field: [msg]})


class CachedPKField(serializers.PrimaryKeyRelatedField):
    """PK-связь с кэшем объектов на время операции (массовый импорт не
    перечитывает один и тот же салон/размер/мероприятие для каждой строки)."""

    def to_internal_value(self, data):
        cache = self.parent_cache()
        if cache is None:
            return super().to_internal_value(data)
        key = (self.queryset.model, str(data))
        if key not in cache:
            cache[key] = super().to_internal_value(data)
        return cache[key]

    def parent_cache(self):
        node = self
        while node is not None and not hasattr(node, '_context'):
            node = node.parent
        ctx = getattr(node, '_context', None) or {}
        return ctx.get('pk_cache')


class BaseMDSerializer(serializers.ModelSerializer):
    """Общая логика. В context: org, user, policy, fields (DirectoryField),
    mode ('list'|'detail'), source ('ui'|'api'|'import')."""

    spec = None  # DictSpec
    serializer_related_field = CachedPKField

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        org = self.context.get('org')
        for name, field in self.fields.items():
            target = getattr(field, 'child_relation', field)
            qs = getattr(target, 'queryset', None)
            if qs is not None and org is not None and hasattr(qs.model, 'organization'):
                target.queryset = qs.model.objects.filter(organization=org)
        self.warnings = []

    # ---------------- helpers ----------------
    @property
    def policy(self):
        return self.context.get('policy')

    @property
    def org(self):
        return self.context['org']

    def can_edit(self, field):
        p = self.policy
        if p is None:
            return True
        return field not in p.hidden and field not in p.readonly

    def can_see(self, field):
        p = self.policy
        return p is None or field not in p.hidden

    def extra_defs(self):
        return [f for f in self.context.get('fields', []) if not f.is_system and not f.is_archived]

    # ---------------- input ----------------
    def to_internal_value(self, data):
        data = dict(data.items()) if hasattr(data, 'items') else data
        p = self.policy
        errors = {}
        # Скрытые поля роли не принимаются; read-only — нельзя менять.
        if p is not None:
            for f in list(data.keys()):
                if f in p.hidden:
                    data.pop(f)
                elif f in p.readonly:
                    cur = self._current_value(f)
                    if not self._same(cur, data[f]):
                        errors[f] = [ERR_RIGHTS]
                    data.pop(f)
        extra_in = {}
        for fd in self.extra_defs():
            if fd.code in data:
                extra_in[fd.code] = data.pop(fd.code)
        try:
            validated = super().to_internal_value(data)
        except serializers.ValidationError as e:
            errors.update(e.detail if isinstance(e.detail, dict) else {'non_field_errors': e.detail})
            validated = {}
        extra = dict(self.instance.extra) if self.instance is not None else {}
        for fd in self.extra_defs():
            if fd.code in extra_in:
                try:
                    extra[fd.code] = fieldtypes.coerce_json_value(
                        fd, extra_in[fd.code],
                        resolve_ref=lambda code, raw: resolve_ref(self.org, code, raw,
                                                                  self.context.get('create_missing', False),
                                                                  self.context.get('user')))
                except DjangoValidationError as e:
                    errors[fd.code] = e.messages
                    continue
            elif self.instance is None and fd.default not in (None, ''):
                extra[fd.code] = fd.default
            val = extra.get(fd.code)
            if fd.required and fieldtypes.is_empty(val):
                errors[fd.code] = ['Обязательное поле']
            elif fd.unique and not fieldtypes.is_empty(val):
                qs = self.Meta.model.objects.filter(organization=self.org, **{f'extra__{fd.code}': val})
                if self.instance is not None:
                    qs = qs.exclude(pk=self.instance.pk)
                if qs.exists():
                    errors[fd.code] = ['Значение должно быть уникальным']
        if errors:
            raise serializers.ValidationError(errors)
        validated['extra'] = extra
        return validated

    def _current_value(self, f):
        if self.instance is None:
            return None
        v = getattr(self.instance, f, None)
        if hasattr(v, 'all'):
            return sorted(str(x.pk) for x in v.all())
        if hasattr(v, 'pk'):
            return str(v.pk)
        return v

    @staticmethod
    def _same(cur, new):
        if fieldtypes.is_empty(cur) and fieldtypes.is_empty(new):
            return True
        if isinstance(cur, list):
            return sorted(map(str, cur)) == sorted(map(str, new or []))
        if isinstance(cur, Decimal) or isinstance(new, (int, float)):
            try:
                return Decimal(str(cur)) == Decimal(str(new))
            except Exception:
                return False
        return str(cur) == str(new)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        code = attrs.get('code', None)
        if code:
            qs = self.Meta.model.objects.filter(organization=self.org, code=code)
            if self.instance is not None:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                _err('code', 'Код уже используется')
        return attrs

    # ---------------- save ----------------
    def create(self, validated_data):
        validated_data['organization'] = self.org
        validated_data['created_by'] = self.context.get('user')
        validated_data['updated_by'] = self.context.get('user')
        return self._save(None, validated_data)

    def update(self, instance, validated_data):
        validated_data['updated_by'] = self.context.get('user')
        return self._save(instance, validated_data)

    def _save(self, instance, data):
        m2m = {}
        for f in self.Meta.model._meta.many_to_many:
            if f.name in data:
                m2m[f.name] = data.pop(f.name)
        try:
            with transaction.atomic():
                if instance is None:
                    instance = self.Meta.model(**data)
                else:
                    for k, v in data.items():
                        setattr(instance, k, v)
                self.before_save(instance)
                instance.save()
                for k, v in m2m.items():
                    getattr(instance, k).set(v)
                self.after_save(instance)
        except IntegrityError as e:
            raise serializers.ValidationError(self.integrity_message(e))
        return instance

    def before_save(self, instance):
        pass

    def after_save(self, instance):
        pass

    def integrity_message(self, e):
        s = str(e)
        if 'code_uniq' in s:
            return {'code': ['Код уже используется']}
        return {'non_field_errors': ['Запись нарушает уникальность: ' + s.split('\n')[0][:200]]}

    # ---------------- output ----------------
    def to_representation(self, instance):
        data = super().to_representation(instance)
        labels = self.context.setdefault('_labels', LabelCache(self.org))
        for name, field in self.fields.items():
            if name not in data:
                continue
            if isinstance(field, serializers.ManyRelatedField):
                data[f'{name}__display'] = [str(x) for x in getattr(instance, name).all()]
            elif isinstance(field, serializers.PrimaryKeyRelatedField):
                rel = getattr(instance, name, None)
                data[f'{name}__display'] = str(rel) if rel is not None else ''
            elif isinstance(field, serializers.ChoiceField):
                data[f'{name}__display'] = dict(field.choices).get(data[name], '') if data[name] else ''
        for fd in self.extra_defs():
            v = (instance.extra or {}).get(fd.code)
            data[fd.code] = v
            if fd.type in ('ref', 'choice'):
                data[f'{fd.code}__display'] = fieldtypes.display_json_value(fd, v, labels)
        data['_title'] = str(instance)
        if self.context.get('mode') == 'detail':
            data['created_by__display'] = getattr(instance.created_by, 'name', '') if instance.created_by_id else ''
            data['updated_by__display'] = getattr(instance.updated_by, 'name', '') if instance.updated_by_id else ''
        p = self.policy
        if p is not None:
            for f in p.hidden:
                data.pop(f, None)
                data.pop(f'{f}__display', None)
        return data


# ============================================================
# Миксины справочников
# ============================================================
class CategoryMixin:
    def validate(self, attrs):
        attrs = super().validate(attrs)
        parent = attrs.get('parent', getattr(self.instance, 'parent', None))
        if parent is not None:
            node, guard = parent, 0
            while node is not None and guard < 10:
                if self.instance is not None and node.pk == self.instance.pk:
                    _err('parent', 'Категория не может быть вложена сама в себя')
                node, guard = node.parent, guard + 1
            depth = parent.depth + 1
            sub = self._subtree_height() if self.instance is not None else 0
            if depth + sub > m.Category.MAX_DEPTH:
                _err('parent', f'Глубина дерева — не больше {m.Category.MAX_DEPTH} уровней')
            if parent.models.exists():
                _err('parent', 'У родительской категории есть модели — модель может быть только в конечной категории')
        prefix = attrs.get('article_prefix')
        if prefix:
            attrs['article_prefix'] = prefix.strip().upper()
        return attrs

    def _subtree_height(self):
        h, frontier = 0, [self.instance.pk]
        while True:
            frontier = list(m.Category.objects.filter(parent_id__in=frontier).values_list('id', flat=True))
            if not frontier:
                return h
            h += 1


class ColorMixin:
    def validate_hex(self, v):
        try:
            validate_hex(v)
        except DjangoValidationError as e:
            raise serializers.ValidationError(e.messages)
        return v.upper() if v else v


class CountryMixin:
    def validate_iso_code(self, v):
        v = (v or '').strip().upper()
        if len(v) != 2 or not v.isalpha():
            raise serializers.ValidationError('Код ISO — две латинские буквы (KZ, TR…)')
        qs = m.Country.objects.filter(organization=self.org, iso_code=v)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError('Страна с таким кодом уже есть')
        return v

    def before_save(self, instance):
        if not instance.code:
            instance.code = instance.iso_code


class SizeMixin:
    def validate(self, attrs):
        attrs = super().validate(attrs)
        system = attrs.get('system', getattr(self.instance, 'system', 'RU'))
        value = (attrs.get('value', getattr(self.instance, 'value', '')) or '').strip()
        qs = m.Size.objects.filter(organization=self.org, system=system, value__iexact=value)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            _err('value', 'Такой размер уже есть')
        return attrs


class StageMixin:
    def validate(self, attrs):
        attrs.pop('system_key', None)  # системный ключ меняет только код
        return super().validate(attrs)


class DepositMixin:
    def validate(self, attrs):
        attrs = super().validate(attrs)
        kind = attrs.get('kind', getattr(self.instance, 'kind', 'percent'))
        value = attrs.get('value', getattr(self.instance, 'value', None))
        if kind == 'percent' and value is not None and value > 100:
            _err('value', 'Процент не больше 100')
        return attrs


class AccountMixin:
    def validate(self, attrs):
        attrs = super().validate(attrs)
        parent = attrs.get('parent')
        node, guard = parent, 0
        while node is not None and guard < 20:
            if self.instance is not None and node.pk == self.instance.pk:
                _err('parent', 'Счёт не может быть вложен сам в себя')
            node, guard = node.parent, guard + 1
        return attrs


class IinBinMixinBase:
    @staticmethod
    def _check_iin(value, field):
        v = (value or '').strip().replace(' ', '')
        if not v:
            return ''
        if not v.isdigit() or len(v) != 12:
            _err(field, 'ИИН/БИН должен состоять из 12 цифр')
        if not iin_bin_checksum_ok(v):
            _err(field, 'Неверная контрольная сумма ИИН/БИН')
        return v


class CounterpartyMixin(IinBinMixinBase):
    roles = serializers.ListField(child=serializers.CharField(), required=False)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if 'bin_iin' in attrs:
            attrs['bin_iin'] = self._check_iin(attrs['bin_iin'], 'bin_iin')
        roles = attrs.get('roles', getattr(self.instance, 'roles', None) if self.instance else None)
        valid = {v for v, _ in m.COUNTERPARTY_ROLE_CHOICES}
        if not roles:
            _err('roles', 'Укажите хотя бы одну роль')
        bad = [r for r in roles if r not in valid]
        if bad:
            _err('roles', f'Неизвестная роль: {", ".join(bad)}')
        if attrs.get('email'):
            try:
                fieldtypes.coerce_json_value(type('E', (), {'type': 'email', 'multiple': False,
                                                            'validation': {}})(), attrs['email'])
            except DjangoValidationError:
                _err('email', 'Некорректный email')
        return attrs

    def to_representation(self, instance):
        d = super().to_representation(instance)
        labels = dict(m.COUNTERPARTY_ROLE_CHOICES)
        d['roles__display'] = [labels.get(r, r) for r in (instance.roles or [])]
        return d


class ClientMixin(IinBinMixinBase):
    """Клиенты: ИИН (контрольная сумма, уникальность), телефон, дубли (МД-20)."""
    iin = serializers.CharField(required=False, allow_blank=True)
    doc_number = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if 'iin' in attrs:
            iin = self._check_iin(attrs['iin'], 'iin')
            attrs['iin'] = iin
            if iin:
                from ..crypto import blind_hash
                qs = m.Client.objects.filter(organization=self.org, iin_hash=blind_hash(iin))
                if self.instance is not None:
                    qs = qs.exclude(pk=self.instance.pk)
                if qs.exists():
                    _err('iin', 'Клиент с таким ИИН уже есть')
        if 'phone' in attrs:
            try:
                attrs['phone'] = normalize_phone(attrs['phone'])
            except DjangoValidationError as e:
                _err('phone', e.messages[0])
        if attrs.get('pd_consent') and not attrs.get('pd_consent_at') and not getattr(self.instance, 'pd_consent_at',
                                                                                      None):
            attrs['pd_consent_at'] = timezone.now()
        self.warnings = duplicate_warnings(self.org, attrs.get('phone'), attrs.get('full_name'),
                                           exclude=self.instance.pk if self.instance else None)
        return attrs

    def to_representation(self, instance):
        d = super().to_representation(instance)
        list_mode = self.context.get('mode') == 'list'
        if self.can_see('iin'):
            d['iin'] = mask_tail(instance.iin) if list_mode else instance.iin
        if self.can_see('doc_number'):
            d['doc_number'] = mask_tail(instance.doc_number) if list_mode else instance.doc_number
        d['phone__display'] = format_phone(instance.phone)
        return d


def duplicate_warnings(org, phone, full_name, exclude=None):
    """Предупреждение о возможном дубле — при похожем телефоне или ФИО."""
    out = []
    qs = m.Client.objects.filter(organization=org, is_active=True)
    if exclude:
        qs = qs.exclude(pk=exclude)
    if phone:
        from ..validators import phone_digits
        dig = phone_digits(phone)
        same = qs.filter(phone_digits__endswith=dig[-10:]) if len(dig) >= 10 else qs.none()
        for c in same[:3]:
            out.append({'field': 'phone', 'id': str(c.pk), 'message': f'Телефон уже есть у клиента «{c.full_name}»'})
    if full_name:
        words = [w for w in full_name.lower().split() if len(w) > 1][:2]
        if words:
            cond = Q()
            for w in words:
                cond &= Q(full_name__icontains=w)
            for c in qs.filter(cond)[:3]:
                if any(x['id'] == str(c.pk) for x in out):
                    continue
                out.append({'field': 'full_name', 'id': str(c.pk),
                            'message': f'Похожий клиент: «{c.full_name}», {format_phone(c.phone)}'})
    return out


class ProductModelMixin:
    """Номенклатура: правила §4.3, §4.6 и МД-20."""
    article = serializers.CharField(required=False, allow_blank=True, max_length=40)
    operations = serializers.ChoiceField(choices=m.OPERATION_CHOICES, required=False)
    return_check_details = serializers.ListField(child=serializers.CharField(max_length=60), required=False)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        inst = self.instance
        get = lambda k: attrs.get(k, getattr(inst, k, None) if inst is not None else None)  # noqa: E731
        category = get('category')
        errors = {}
        if category is not None and (inst is None or 'category' in attrs and category != inst.category):
            if not category.is_selectable(self.org):
                errors['category'] = ['Категория отключена или находится в выключенном разделе']
            elif not category.is_leaf():
                errors['category'] = ['Выберите конечную категорию (без подкатегорий)']
        # Мероприятия — минимум одно
        if 'events' in attrs or inst is None:
            if not attrs.get('events'):
                errors['events'] = ['Укажите хотя бы одно мероприятие']
        # Виды должны быть применимы к категории (МД-9)
        styles = attrs.get('styles') if 'styles' in attrs else (list(inst.styles.all()) if inst else [])
        if category is not None and styles:
            bad = [s.name for s in styles if not s.applicable_to(category)]
            if bad:
                errors['styles'] = [f'Не применимы к категории «{category.name}»: {", ".join(bad)}']
        # Операции: по умолчанию из категории; категория ограничивает допустимые
        ops = attrs.get('operations') or (inst.operations if inst else None)
        if category is not None:
            cat_ops = category.effective_operations()
            if not ops:
                ops = cat_ops
                attrs['operations'] = ops
            if cat_ops != m.OPERATION_BOTH and ops != cat_ops:
                errors['operations'] = [f'Категория «{category.name}» допускает только: '
                                        f'{dict(m.OPERATION_CHOICES)[cat_ops].lower()}']
        # Цены (МД-20)
        rent, min_rent, sale = get('rent_price'), get('min_rent_price'), get('sale_price')
        can_prices = self.can_edit('rent_price')
        if ops in (m.OPERATION_RENT, m.OPERATION_BOTH) and rent is None:
            if can_prices:
                errors['rent_price'] = ['Цена аренды обязательна, если операции включают аренду']
            else:
                self.warnings.append({'field': 'rent_price', 'message': 'Цену аренды заполнит администратор'})
        if ops in (m.OPERATION_SALE, m.OPERATION_BOTH) and sale is None:
            if can_prices:
                errors['sale_price'] = ['Цена продажи обязательна, если операции включают продажу']
            else:
                self.warnings.append({'field': 'sale_price', 'message': 'Цену продажи заполнит администратор'})
        for k in ('rent_price', 'min_rent_price', 'sale_price'):
            v = get(k)
            if v is not None and v < 0:
                errors[k] = ['Цена не может быть отрицательной']
        if rent is not None and min_rent is not None and min_rent > rent:
            errors['min_rent_price'] = ['Минимальная цена аренды не может быть больше базовой']
        resource = get('resource')
        if resource is not None and resource <= 0:
            errors['resource'] = ['Ресурс должен быть больше 0']
        # Страна — по умолчанию из производителя
        if attrs.get('manufacturer') and not get('country') and attrs['manufacturer'].country_id:
            attrs['country'] = attrs['manufacturer'].country
        # Артикул: уникальный в организации
        art = (attrs.get('article') or '').strip()
        if 'article' in attrs:
            attrs['article'] = art
            if not art and inst is not None:
                errors['article'] = ['Артикул обязателен']
        if art:
            qs = m.ProductModel.objects.filter(organization=self.org, article__iexact=art)
            if inst is not None:
                qs = qs.exclude(pk=inst.pk)
            if qs.exists():
                errors['article'] = ['Модель с таким артикулом уже есть']
        if errors:
            raise serializers.ValidationError(errors)
        return attrs

    def before_save(self, instance):
        if not instance.article:
            instance.article = articles.generate_model_article(self.org, instance.category, instance.country)
            while m.ProductModel.objects.filter(organization=self.org, article=instance.article).exists():
                instance.article = articles.generate_model_article(self.org, instance.category, instance.country)
        else:
            articles.register_manual_article(self.org, instance.category, instance.article, instance.country)

    def integrity_message(self, e):
        if 'article' in str(e):
            return {'article': ['Модель с таким артикулом уже есть']}
        return super().integrity_message(e)

    def to_representation(self, instance):
        d = super().to_representation(instance)
        photo = instance.main_photo
        d['main_photo'] = photo_urls(photo) if photo else None
        d['category__path'] = instance.category.path_name()
        if self.context.get('mode') == 'detail':
            d['items_count'] = instance.items.filter(is_active=True).count()
            d['effective'] = {'size_required': instance.category.effective_size_required(),
                              'category_operations': instance.category.effective_operations()}
        return d


class ItemMixin:
    """Экземпляр: бирка, артикул, обязательность размера/поставщика (§4.4)."""
    tag = serializers.CharField(read_only=True)
    rent_count = serializers.IntegerField(required=False, min_value=0)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        inst = self.instance
        get = lambda k: attrs.get(k, getattr(inst, k, None) if inst is not None else None)  # noqa: E731
        errors = {}
        model = get('model')
        if inst is not None and 'rent_count' in attrs and attrs['rent_count'] != inst.rent_count \
                and self.context.get('source') != 'import':
            errors['rent_count'] = ['Число аренд считает система']
        if model is not None:
            if not model.is_active and (inst is None or model != inst.model):
                errors['model'] = ['Модель в архиве']
            elif model.category.effective_size_required() and not get('size'):
                errors['size'] = [f'Для категории «{model.category.name}» размер обязателен']
            if model.acquisition == 'purchase' and not get('supplier') and self.can_edit('supplier'):
                errors['supplier'] = ['Поставщик обязателен при закупе']
        cost = get('cost')
        if cost is not None and cost < 0:
            errors['cost'] = ['Стоимость не может быть отрицательной']
        if inst is None:
            if not attrs.get('stage'):
                cache = self.context.get('pk_cache')
                st = cache.get('default_stage') if cache is not None else None
                if st is None:
                    st = m.Stage.objects.filter(organization=self.org, system_key='in_salon').first()
                    if cache is not None:
                        cache['default_stage'] = st
                if st:
                    attrs['stage'] = st
                else:
                    errors['stage'] = ['Обязательное поле']
            if not attrs.get('received_at'):
                attrs['received_at'] = timezone.localdate()
        bc = attrs.get('barcode')
        if bc:
            qs = m.Item.objects.filter(organization=self.org, barcode=bc)
            if inst is not None:
                qs = qs.exclude(pk=inst.pk)
            if qs.exists():
                errors['barcode'] = ['Штрихкод уже назначен другому экземпляру']
        if errors:
            raise serializers.ValidationError(errors)
        return attrs

    def before_save(self, instance):
        if not instance.tag:
            instance.tag = articles.new_tag(self.org)

    def to_representation(self, instance):
        d = super().to_representation(instance)
        d['article'] = instance.article
        d['model__display'] = f'{instance.model.article} · {instance.model.name}'
        d['model__article'] = instance.model.article
        d['model__name'] = instance.model.name
        link = instance.active_kit_link
        d['kit'] = str(link.kit_id) if link else None
        d['kit__display'] = f'{link.kit.code} {link.kit.name}' if link else ''
        photo = instance.photos.order_by('-is_main', 'order').first() or instance.model.main_photo
        d['main_photo'] = photo_urls(photo) if photo else None
        if self.context.get('mode') == 'detail':
            mm = instance.model
            d['effective_prices'] = {
                'rent_price': instance.rent_price_override if instance.rent_price_override is not None else mm.rent_price,
                'sale_price': instance.sale_price_override if instance.sale_price_override is not None else mm.sale_price,
                'min_rent_price': mm.min_rent_price,
            }
            d['resource_left'] = max(0, (mm.resource or 0) - instance.rent_count)
        return d


class KitComponentSerializer(serializers.Serializer):
    item = serializers.UUIDField()
    role = serializers.ChoiceField(choices=m.KIT_ROLE_CHOICES, default='other')


class KitMixin:
    """Комплект: экземпляр — только в одном активном комплекте (МД-18)."""
    code = serializers.CharField(required=False, allow_blank=True, max_length=64)
    components = KitComponentSerializer(many=True, required=False)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        comps = attrs.get('components')
        if comps is None and self.instance is None:
            comps = []
        errors = {}
        if comps is not None:
            main = attrs.get('main_item', getattr(self.instance, 'main_item', None))
            ids = [str(c['item']) for c in comps]
            if main is not None and str(main.pk) not in ids:
                comps.insert(0, {'item': main.pk, 'role': 'base' if main.model.category.effective_section() == 'uzatu'
                                 else 'dress'})
                ids.insert(0, str(main.pk))
            if not comps:
                errors['components'] = ['Добавьте экземпляры в состав комплекта']
            if len(set(ids)) != len(ids):
                errors['components'] = ['Экземпляр указан в составе дважды']
            items = {str(i.pk): i for i in m.Item.objects.filter(organization=self.org, pk__in=ids)
                     .select_related('model')}
            msgs = []
            for c in comps:
                it = items.get(str(c['item']))
                if it is None:
                    msgs.append(f'Экземпляр {c["item"]} не найден')
                    continue
                if not it.is_active or it.status != 'active':
                    msgs.append(f'Экземпляр {it.tag} не активен')
                busy = m.KitItem.objects.filter(item=it, kit_active=True)
                if self.instance is not None:
                    busy = busy.exclude(kit=self.instance)
                b = busy.select_related('kit').first()
                if b:
                    msgs.append(f'Экземпляр {it.tag} ({it.article}) уже входит в активный комплект {b.kit.code}')
                c['_obj'] = it
            if msgs:
                errors['components'] = msgs
            attrs['components'] = comps
        if errors:
            raise serializers.ValidationError(errors)
        return attrs

    def _save(self, instance, data):
        comps = data.pop('components', None)
        self._comps = comps
        return super()._save(instance, data)

    def before_save(self, instance):
        if not instance.code:
            instance.code = articles.new_kit_code(self.org)

    def after_save(self, instance):
        comps = getattr(self, '_comps', None)
        if comps is None:
            return
        instance.components.all().delete()
        for i, c in enumerate(comps):
            m.KitItem.objects.create(organization=self.org, kit=instance, item=c['_obj'], role=c['role'],
                                     order=i, kit_active=instance.is_active)

    def integrity_message(self, e):
        if 'md_item_one_active_kit' in str(e):
            return {'components': ['Экземпляр уже входит в другой активный комплект']}
        return super().integrity_message(e)

    def to_representation(self, instance):
        d = super().to_representation(instance)
        roles = dict(m.KIT_ROLE_CHOICES)
        comps = []
        total = Decimal('0')
        for c in instance.components.select_related('item__model', 'item__size').all():
            it = c.item
            rp = it.rent_price_override if it.rent_price_override is not None else it.model.rent_price
            total += rp or 0
            comps.append({'item': str(it.pk), 'role': c.role, 'role__display': roles.get(c.role, c.role),
                          'tag': it.tag, 'article': it.article, 'name': it.model.name,
                          'rent_price': rp})
        d['components'] = comps
        d['components_rent_total'] = total
        return d


MIXINS = {
    'categories': [CategoryMixin], 'colors': [ColorMixin], 'countries': [CountryMixin], 'sizes': [SizeMixin],
    'stages': [StageMixin], 'deposit_options': [DepositMixin], 'accounts': [AccountMixin],
    'counterparties': [CounterpartyMixin], 'clients': [ClientMixin], 'models': [ProductModelMixin],
    'items': [ItemMixin], 'kits': [KitMixin],
}

_CACHE = {}

# Поля, у которых есть значение по умолчанию на уровне правил (не обязательны во вводе)
EXTRA_KWARGS = {
    'items': {'stage': {'required': False}, 'received_at': {'required': False}},
}


def make_serializer(spec):
    if spec.code in _CACHE:
        return _CACHE[spec.code]
    model_fields = {f.name for f in spec.model._meta.get_fields()}
    field_names = list(BASE_OUT)
    for f in spec.fields:
        if f['code'] in model_fields and f['code'] not in field_names:
            field_names.append(f['code'])
    if 'code' in model_fields and 'code' not in field_names:
        field_names.append('code')
    if spec.code == 'kits':
        field_names.append('components')
    ro = ['id', 'created_at', 'updated_at', 'is_active']
    if spec.code == 'stages':
        ro.append('system_key')
    if spec.code == 'items':
        ro.append('tag')
    extra_kwargs = EXTRA_KWARGS.get(spec.code, {})
    meta = type('Meta', (), {'model': spec.model, 'fields': field_names, 'read_only_fields': ro,
                             'validators': [], 'extra_kwargs': extra_kwargs})
    bases = tuple(MIXINS.get(spec.code, [])) + (BaseMDSerializer,)
    attrs = {'Meta': meta, 'spec': spec}
    for mixin in MIXINS.get(spec.code, []):
        for k, v in list(vars(mixin).items()):
            if isinstance(v, serializers.Field):
                attrs[k] = v
    cls = type(f'{spec.model.__name__}Serializer', bases, attrs)
    _CACHE[spec.code] = cls
    return cls


# ---------------- фото: подписанные ссылки ----------------
def photo_urls(photo):
    from ..photos import signed_url
    if photo is None:
        return None
    return {
        'id': str(photo.id),
        'url': signed_url(photo, 'file'),
        'thumb_300': signed_url(photo, 'thumb_300') if photo.thumb_300 else signed_url(photo, 'file'),
        'thumb_1200': signed_url(photo, 'thumb_1200') if photo.thumb_1200 else signed_url(photo, 'file'),
        'photo_type': str(photo.photo_type_id) if photo.photo_type_id else None,
        'photo_type__display': photo.photo_type.name if photo.photo_type_id else '',
        'order': photo.order, 'is_main': photo.is_main, 'name': photo.original_name,
    }
