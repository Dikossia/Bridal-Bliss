"""
Начальное наполнение организации (МД-4, критерий приёмки №1).

seed_organization(org) создаёт системные справочники (строки Directory +
поля), матрицу прав (§6) и начальные данные из §4. Идемпотентна: повторный
вызов ничего не дублирует и только досоздаёт недостающее (удобно после
обновлений, когда в реестре появляются новые поля).
"""
from decimal import Decimal

from django.db import transaction

from accounts.models import Membership

from . import models as m
from .registry import (COMMON, ORG_SETTINGS_DICTS, PRICE_FIELDS, PRODUCT_CLASSIFIERS, PRODUCT_CORE,
                       PURCHASE_FIELDS, SPECS)

ROLES = [r for r, _ in Membership.ROLE_CHOICES]

# ------------------------------------------------------------
# Матрица прав по умолчанию (§6). Ключи: view, create, update, archive,
# import, export, history ('all'|'own'|'none'), hidden, readonly.
# ------------------------------------------------------------
FULL = dict(view=True, create=True, update=True, archive=True, imp=True, export=True, history='all')
VIEW_ONLY = dict(view=True, create=False, update=False, archive=False, imp=False, export=False, history='all')
NONE = dict(view=False, create=False, update=False, archive=False, imp=False, export=False, history='none')


def default_policy(role, code):
    """Возвращает dict прав роли на справочник по таблице §6."""
    if role in ('owner',):
        return dict(FULL)
    if role == 'admin':
        if code == 'accounts':                       # Счета: администратор — просмотр
            p = dict(VIEW_ONLY)
            p['export'] = True
            return p
        return dict(FULL)
    if role == 'seller':
        # Импорт, экспорт, архивирование — нет; история — своих записей.
        if code in PRODUCT_CORE or code in PRODUCT_CLASSIFIERS:
            p = dict(view=True, create=True, update=True, archive=False, imp=False, export=False, history='own')
            p['readonly'] = list(PRICE_FIELDS.get(code, []))      # цены — только просмотр
            p['hidden'] = list(PURCHASE_FIELDS.get(code, []))     # стоимость поступления, поставщик — нет
            return p
        if code == 'clients':
            return dict(view=True, create=True, update=True, archive=False, imp=False, export=False, history='own')
        if code in ('counterparties', 'deposit_options') or code in ORG_SETTINGS_DICTS or code in COMMON:
            p = dict(VIEW_ONLY)
            p['history'] = 'own'
            return p
        if code == 'accounts':
            return dict(NONE)
        # пользовательские справочники
        return dict(view=True, create=True, update=True, archive=False, imp=False, export=False, history='own')
    if role == 'accountant':
        if code in ('accounts', 'counterparties'):
            return dict(view=True, create=True, update=True, archive=False, imp=True, export=True, history='all')
        if code == 'clients':
            return dict(view=True, create=False, update=False, archive=False, imp=False, export=True, history='all')
        if code == 'deposit_options':
            return dict(view=True, create=True, update=True, archive=False, imp=False, export=True, history='all')
        # товар и прочее — просмотр (цены — просмотр, закупка — видна)
        p = dict(VIEW_ONLY)
        p['export'] = True
        return p
    return dict(NONE)


def ensure_role_policies(org, codes):
    existing = set(m.RolePolicy.objects.filter(organization=org).values_list('role', 'directory_code'))
    to_create = []
    for role in ROLES:
        for code in codes:
            if (role, code) in existing:
                continue
            p = default_policy(role, code)
            to_create.append(m.RolePolicy(
                organization=org, role=role, directory_code=code,
                can_view=p['view'], can_create=p['create'], can_update=p['update'],
                can_archive=p['archive'], can_import=p['imp'], can_export=p['export'],
                history=p['history'], hidden_fields=p.get('hidden', []), readonly_fields=p.get('readonly', []),
            ))
    m.RolePolicy.objects.bulk_create(to_create)


# ------------------------------------------------------------
# Системные Directory + DirectoryField
# ------------------------------------------------------------
FIELD_ATTRS = ['name', 'type', 'required', 'hint', 'group', 'show_in_list', 'searchable', 'filterable',
               'options', 'multiple', 'ref_directory', 'validation', 'readonly', 'default']


def sync_system_directories(org):
    for spec in SPECS:
        d, created = m.Directory.objects.get_or_create(
            organization=org, code=spec.code,
            defaults=dict(name=spec.name, menu_group=spec.group, icon=spec.icon, is_system=True,
                          is_hierarchical=spec.hierarchical, display_field=spec.display_field,
                          supports_photo=spec.supports_photo, order=spec.order, description=spec.description))
        existing = {f.code: f for f in d.fields.all()}
        for idx, fs in enumerate(spec.fields):
            f = existing.get(fs['code'])
            vals = {k: fs[k] for k in FIELD_ATTRS if k in fs}
            vals.setdefault('options', [])
            vals.setdefault('validation', {})
            if f is None:
                m.DirectoryField.objects.create(organization=org, directory=d, code=fs['code'], is_system=True,
                                                order=(idx + 1) * 10, **vals)
            else:
                # Подпись/порядок/группу администратор мог поменять — их не трогаем;
                # «жёсткие» атрибуты системного поля синхронизируем с кодом.
                changed = False
                for k in ['type', 'multiple', 'ref_directory', 'readonly', 'options']:
                    if k in vals and getattr(f, k) != vals[k]:
                        setattr(f, k, vals[k])
                        changed = True
                if not f.is_system:
                    f.is_system, changed = True, True
                if changed:
                    f.save()
    ensure_role_policies(org, [s.code for s in SPECS])


# ------------------------------------------------------------
# Начальные данные (§4)
# ------------------------------------------------------------
COUNTRIES = [('KZ', 'Казахстан'), ('TR', 'Турция'), ('CN', 'Китай'), ('KG', 'Кыргызстан'),
             ('AE', 'ОАЭ'), ('RU', 'Россия'), ('UZ', 'Узбекистан')]

# (name, prefix, operations, size_required, section, children, is_enabled)
CATEGORIES = [
    ('Свадебные платья', 'СВ', 'both', True, '', [], True),
    ('Ұзату', '', '', None, 'uzatu', [
        ('База', 'БЗ', 'both', True),
        ('Қамзол', 'КМ', 'rent', None),
        ('Шапан', 'ШП', 'rent', None),
        ('Корсет', 'КР', 'rent', True),
        ('Тақия', 'ТК', 'rent', None),
        ('Сәукеле', 'СК', 'rent', None),
    ], True),
    ('Фата', 'ФТ', 'sale', None, '', [], True),
    ('Аксессуары', 'АК', 'both', None, '', [
        ('Диадемы', '', '', None), ('Серьги', '', '', None), ('Перчатки', '', '', None),
    ], True),
    ('Кольцо под платье (кринолин)', 'КЛ', 'both', None, '', [], True),
    ('Букеты', 'БК', 'sale', None, '', [], True),
    ('Бомбоньерки', 'ББ', 'sale', None, '', [], True),
    ('Обувь', 'ОБ', 'both', None, 'shoes', [], True),
]

EVENTS = ['Свадьба', 'Ұзату', 'ЗАГС / регистрация / венчание', 'Выпускной', 'Фотосессия', 'Девичник', 'Прочие']

DRESS_CATS = ['Свадебные платья', 'База']
STYLES = [
    ('Европейское', DRESS_CATS), ('Королевское', DRESS_CATS), ('Воздушное', DRESS_CATS),
    ('Кружевное', DRESS_CATS + ['Фата']), ('Рыбка', DRESS_CATS), ('С бисером', DRESS_CATS),
    ('Классическое', DRESS_CATS + ['Фата']),
]
SIZES = ['40', '42', '44', '46', '48', '50', '52']
COLORS = [('Белый', '#FFFFFF'), ('Айвори', '#FFFFF0'), ('Шампань', '#F7E7CE'), ('Красный', '#C0392B'),
          ('Бордовый', '#800020'), ('Золотой', '#D4AF37'), ('Розовый', '#F4C2C2'), ('Голубой', '#A7C7E7')]
PHOTO_TYPES = ['Главное', 'На манекене', 'На модели', 'Спина', 'Деталь узора']
DEFECT_TYPES = [('Порыв', True), ('Сломанный замок', True), ('Пятно', False), ('Потеря детали', True)]
DAY = 24 * 60
# (system_key, name, minutes, max_minutes, available, optional, terminal)
STAGES = [
    ('in_salon', 'В салоне', None, None, True, False, False),
    ('fitting', 'Примерка', 60, None, True, False, False),
    ('restoration_before', 'Реставрация перед выдачей', DAY, None, False, True, False),
    ('cleaning_before', 'Химчистка перед выдачей', DAY, None, False, False, False),
    ('rent', 'Аренда', 3 * DAY, 4 * DAY, False, False, False),
    ('return', 'Возврат (ожидает обработки)', DAY, None, False, False, False),
    ('restoration_after', 'Реставрация после возврата', DAY, 2 * DAY, False, True, False),
    ('cleaning_after', 'Химчистка после возврата', DAY, None, False, False, False),
    ('retired', 'Выбыл: продан, списан, разобран', None, None, False, False, True),
]
SALONS = [('Бутик 1', 'ТЦ «Адем»'), ('Бутик 2', 'ТЦ «Адем»')]
DEPOSITS = [('Залог 10%', 10), ('Залог 20%', 20), ('Залог 50%', 50)]
# (group, pnl, cashflow, func_area, [items])
ACCOUNTS = [
    ('Доходы', 'income', 'inflow', '', ['Аренда платьев', 'Продажа новых платьев', 'Продажа б/у платьев',
                                         'Продажа фаты, аксессуаров и букетов', 'Удержания из залога за ущерб']),
    ('Помещение и связь', 'expense', 'outflow', 'admin',
     ['Аренда помещения', 'Коммунальные услуги', 'Интернет', 'Телефон']),
    ('Уход за платьями', 'expense', 'outflow', 'cost_of_services', ['Химчистка', 'Реставрация и услуги швеи']),
    ('Фотосессия', 'expense', 'outflow', 'selling',
     ['Фотограф', 'Модель', 'Макияж', 'Причёска', 'Аренда студии', 'Аренда транспорта']),
    ('Логистика', 'expense', 'outflow', 'logistics', ['Доставка платьев', 'Транспортные расходы']),
    ('Маркетинг', 'expense', 'outflow', 'selling', ['Таргетированная реклама', 'Услуги маркетолога']),
    ('Прочие расходы', 'expense', 'outflow', 'admin', []),
]


def _get_or_create(model, org, lookup, **defaults):
    obj = model.objects.filter(organization=org, **lookup).first()
    if obj:
        return obj, False
    return model.objects.create(organization=org, **lookup, **defaults), True


def seed_initial_data(org):
    countries = {}
    for i, (iso, name) in enumerate(COUNTRIES):
        countries[iso], _ = _get_or_create(m.Country, org, {'iso_code': iso}, name=name, code=iso)

    cats = {}
    for i, (name, prefix, ops, size_req, section, children, enabled) in enumerate(CATEGORIES):
        parent, _ = _get_or_create(m.Category, org, {'name': name, 'parent': None},
                                   article_prefix=prefix, operations=ops, size_required=size_req,
                                   section=section, is_enabled=enabled, order=(i + 1) * 10)
        cats[name] = parent
        for j, (cname, cprefix, cops, csize) in enumerate(children):
            c, _ = _get_or_create(m.Category, org, {'name': cname, 'parent': parent},
                                  article_prefix=cprefix, operations=cops, size_required=csize, order=(j + 1) * 10)
            cats[cname] = c

    for i, name in enumerate(EVENTS):
        _get_or_create(m.Event, org, {'name': name}, order=(i + 1) * 10)

    for i, (name, cat_names) in enumerate(STYLES):
        st, created = _get_or_create(m.Style, org, {'name': name}, order=(i + 1) * 10)
        if created:
            st.categories.set([cats[c] for c in cat_names if c in cats])

    for i, v in enumerate(SIZES):
        _get_or_create(m.Size, org, {'system': 'RU', 'value': v}, order=(i + 1) * 10)
    for name, hx in COLORS:
        _get_or_create(m.Color, org, {'name': name}, hex=hx)
    _get_or_create(m.Manufacturer, org, {'name': 'Собственный пошив'}, country=countries['KZ'])
    for i, name in enumerate(PHOTO_TYPES):
        _get_or_create(m.PhotoType, org, {'name': name}, order=(i + 1) * 10)
    for name, restor in DEFECT_TYPES:
        _get_or_create(m.DefectType, org, {'name': name}, requires_restoration=restor)
    for i, (key, name, mins, maxm, avail, opt, term) in enumerate(STAGES):
        _get_or_create(m.Stage, org, {'system_key': key}, name=name, duration_minutes=mins,
                       duration_max_minutes=maxm, is_available=avail, is_optional=opt, is_terminal=term,
                       order=(i + 1) * 10)
    for name, addr in SALONS:
        _get_or_create(m.Salon, org, {'name': name}, address=addr)
    for name, val in DEPOSITS:
        _get_or_create(m.DepositOption, org, {'name': name}, kind='percent', value=Decimal(val))
    for i, (group, pnl, cf, fa, items) in enumerate(ACCOUNTS):
        g, _ = _get_or_create(m.Account, org, {'name': group, 'parent': None},
                              pnl=pnl, cashflow=cf, func_area=fa, order=(i + 1) * 10)
        for j, name in enumerate(items):
            _get_or_create(m.Account, org, {'name': name, 'parent': g},
                           pnl=pnl, cashflow=cf, func_area=fa, order=(j + 1) * 10)


@transaction.atomic
def seed_organization(org):
    sync_system_directories(org)
    seed_initial_data(org)
    settings = dict(org.settings or {})
    if 'sections' not in settings:
        settings['sections'] = dict(org.DEFAULT_SECTIONS)
        org.settings = settings
        org.save(update_fields=['settings'])
