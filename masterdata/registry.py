"""
Реестр системных справочников (§4.2).

Описание каждого справочника — ДАННЫЕ: по ним сидируются строки Directory /
DirectoryField организации (подписи и порядок потом можно менять в
«Структуре», МД-10), строится API (поиск, фильтры, ключи импорта) и UI.
"""
from dataclasses import dataclass, field
from typing import Optional

from . import models as m


def F(code, name, type='string', **kw):
    d = {'code': code, 'name': name, 'type': type, 'group': kw.pop('group', 'Основное')}
    d.update(kw)
    return d


def choices(ch):
    return [{'value': v, 'label': lbl} for v, lbl in ch if v != '']


@dataclass
class DictSpec:
    code: str
    model: type
    name: str
    group: str
    icon: str
    fields: list
    display_field: str = 'name'
    hierarchical: bool = False
    supports_photo: bool = False
    search: list = field(default_factory=lambda: ['name'])
    ordering: list = field(default_factory=list)
    select_related: list = field(default_factory=list)
    prefetch: list = field(default_factory=list)
    import_keys: list = field(default_factory=lambda: ['code', 'name'])
    order: int = 0
    tabs: list = field(default_factory=list)  # доп. вкладки карточки (UI)
    description: str = ''

    @property
    def field_codes(self):
        return [f['code'] for f in self.fields]

    def field(self, code) -> Optional[dict]:
        for f in self.fields:
            if f['code'] == code:
                return f
        return None


CODE = F('code', 'Код', hint='Уникальный в организации, необязательный', show_in_list=False, searchable=True)
ORDER = F('order', 'Порядок', 'integer', show_in_list=False)

SPECS = [
    # ---------------- Товар ----------------
    DictSpec(
        'models', m.ProductModel, 'Модели', 'product', '👗', order=1,
        description='Номенклатура: описание товара как модели',
        display_field='name', supports_photo=True,
        search=['article', 'name', 'manufacturer_article'],
        ordering=['article'],
        select_related=['category', 'manufacturer', 'country', 'color'],
        prefetch=['events', 'styles', 'photos'],
        import_keys=['article'],
        tabs=['photos', 'items', 'kits', 'history'],
        fields=[
            F('article', 'Артикул модели', searchable=True, required=False,
              hint='Пусто — сгенерируется по маске категории (СВ-117)'),
            F('name', 'Наименование', required=True, searchable=True),
            F('category', 'Категория', 'ref', ref_directory='categories', required=True,
              group='Классификация', filterable=True, validation={'ref_filter': 'leaf_selectable'}),
            F('events', 'Мероприятия', 'ref', ref_directory='events', multiple=True, required=True,
              group='Классификация', filterable=True, hint='Минимум одно'),
            F('styles', 'Виды (стили)', 'ref', ref_directory='styles', multiple=True,
              group='Классификация', filterable=True, validation={'ref_filter': 'styles_for_category'}),
            F('manufacturer', 'Производитель', 'ref', ref_directory='manufacturers', show_in_list=False),
            F('country', 'Страна происхождения', 'ref', ref_directory='countries', show_in_list=False,
              hint='По умолчанию — из производителя'),
            F('manufacturer_article', 'Артикул производителя', show_in_list=False, searchable=True),
            F('acquisition', 'Способ поступления', 'choice', required=True, options=choices(m.ACQUISITION_CHOICES),
              filterable=True, show_in_list=False),
            F('operations', 'Операции', 'choice', required=True, options=choices(m.OPERATION_CHOICES),
              filterable=True, hint='По умолчанию — из категории'),
            F('color', 'Цвет', 'ref', ref_directory='colors', filterable=True, show_in_list=False),
            F('rent_price', 'Цена аренды, ₸', 'money', group='Цены', filterable=True),
            F('min_rent_price', 'Минимальная цена аренды, ₸', 'money', group='Цены', show_in_list=False,
              hint='Нижняя граница скидки для продавца; не больше базовой'),
            F('sale_price', 'Цена продажи, ₸', 'money', group='Цены', filterable=True),
            F('resource', 'Ресурс, аренд', 'integer', group='Цены', show_in_list=False, default=10,
              hint='По умолчанию 10; основа амортизации'),
            F('return_check_details', 'Детали для проверки при возврате', 'string', multiple=True,
              show_in_list=False, hint='Перышко, пояс, жилетка…'),
            F('description', 'Описание', 'text', show_in_list=False),
            F('show_in_catalog', 'Показывать в каталоге', 'bool', show_in_list=False),
        ]),
    DictSpec(
        'items', m.Item, 'Экземпляры', 'product', '🏷️', order=2,
        description='Физические единицы с биркой',
        display_field='tag', supports_photo=True,
        search=['tag', 'barcode', 'model__article', 'model__name'],
        ordering=['tag'],
        select_related=['model', 'model__category', 'size', 'salon', 'stage', 'supplier'],
        prefetch=['photos'],
        import_keys=['tag', 'barcode'],
        tabs=['photos', 'history'],
        fields=[
            F('tag', 'Бирка', readonly=True, searchable=True, hint='Генерируется автоматически'),
            F('article', 'Артикул экземпляра', 'computed', readonly=True, searchable=True),
            F('model', 'Модель', 'ref', ref_directory='models', required=True, filterable=True),
            F('size', 'Размер', 'ref', ref_directory='sizes', filterable=True,
              hint='Обязателен, если категория требует размер'),
            F('length_cm', 'Длина / рост, см', 'decimal', show_in_list=False),
            F('barcode', 'Штрихкод', searchable=True, show_in_list=False),
            F('salon', 'Салон', 'ref', ref_directory='salons', required=True, filterable=True),
            F('condition', 'Состояние', 'choice', required=True, options=choices(m.CONDITION_CHOICES),
              filterable=True),
            F('status', 'Статус', 'choice', required=True, options=choices(m.ITEM_STATUS_CHOICES), filterable=True),
            F('stage', 'Текущая стадия', 'ref', ref_directory='stages', required=True, filterable=True),
            F('received_at', 'Дата поступления', 'date', required=True, group='Поступление', show_in_list=False),
            F('supplier', 'Поставщик', 'ref', ref_directory='counterparties', group='Поступление',
              show_in_list=False, hint='Обязателен при закупе'),
            F('cost', 'Стоимость поступления, ₸', 'money', group='Поступление', show_in_list=False),
            F('rent_count', 'Выдано в аренду, раз', 'integer', group='Поступление', show_in_list=False,
              readonly=True, hint='Начальное значение — при импорте, далее считает система'),
            F('kit', 'Комплект', 'computed', readonly=True, show_in_list=False),
            F('rent_price_override', 'Индивидуальная цена аренды, ₸', 'money', group='Цены', show_in_list=False),
            F('sale_price_override', 'Индивидуальная цена продажи, ₸', 'money', group='Цены', show_in_list=False),
            F('note', 'Примечание', 'text', show_in_list=False),
        ]),
    DictSpec(
        'kits', m.Kit, 'Комплекты', 'product', '🧺', order=3,
        description='Наборы экземпляров, выдаваемых вместе',
        display_field='name', search=['code', 'name'], ordering=['code'],
        select_related=['main_item', 'main_item__model'], prefetch=['components__item__model'],
        import_keys=['code'], tabs=['history'],
        fields=[
            F('code', 'Код комплекта', searchable=True, hint='Пусто — сгенерируется (КТ-012)'),
            F('name', 'Наименование', required=True, searchable=True),
            F('main_item', 'Основной экземпляр', 'ref', ref_directory='items', hint='Обычно база или платье'),
            F('components', 'Состав', 'computed', show_in_list=False),
            F('price', 'Цена комплекта, ₸', 'money', hint='Если отличается от суммы частей'),
            F('can_split', 'Можно выдавать по частям', 'bool', default=True),
        ]),
    DictSpec(
        'categories', m.Category, 'Категории', 'product', '🗂️', order=4, hierarchical=True,
        search=['name', 'article_prefix', 'code'], ordering=['order', 'name'], select_related=['parent'],
        fields=[
            F('name', 'Название', required=True, searchable=True),
            F('parent', 'Родитель', 'ref', ref_directory='categories', hint='Глубина дерева — до 3 уровней'),
            F('article_prefix', 'Префикс артикула', hint='СВ, БЗ, КМ… Пусто — как у родителя'),
            F('operations', 'Операции по умолчанию', 'choice', options=choices(m.OPERATION_CHOICES)),
            F('size_required', 'Размер обязателен', 'bool'),
            F('section', 'Раздел', 'choice', options=choices(m.SECTION_CHOICES), filterable=True,
              hint='Раздел включается в настройках организации'),
            F('is_enabled', 'Включена', 'bool', default=True, filterable=True),
            F('model_mask', 'Маска артикула модели', show_in_list=False, hint='{PREFIX}-{SEQ:3}'),
            F('item_mask', 'Маска артикула экземпляра', show_in_list=False, hint='{ARTICLE}-{SIZE}'),
            ORDER, CODE,
        ]),
    DictSpec('events', m.Event, 'Мероприятия', 'product', '💍', order=5, ordering=['order', 'name'],
             fields=[F('name', 'Название', required=True, searchable=True), ORDER, CODE]),
    DictSpec('styles', m.Style, 'Виды', 'product', '✨', order=6, ordering=['order', 'name'],
             prefetch=['categories'],
             fields=[F('name', 'Название', required=True, searchable=True),
                     F('categories', 'Применимые категории', 'ref', ref_directory='categories', multiple=True,
                       hint='Пусто — применим ко всем'),
                     ORDER, CODE]),
    DictSpec('sizes', m.Size, 'Размеры', 'product', '📏', order=7, display_field='value',
             search=['value'], ordering=['system', 'order', 'value'], import_keys=['code', 'value'],
             fields=[F('system', 'Система', 'choice', required=True, options=choices(m.SIZE_SYSTEMS),
                       filterable=True),
                     F('value', 'Значение', required=True, searchable=True), ORDER, CODE]),
    DictSpec('colors', m.Color, 'Цвета', 'product', '🎨', order=8,
             fields=[F('name', 'Название', required=True, searchable=True),
                     F('hex', 'HEX', validation={'mask': r'^#[0-9A-Fa-f]{6}$'}, hint='#FFFFFF'), CODE]),
    DictSpec('manufacturers', m.Manufacturer, 'Производители', 'product', '🏭', order=9,
             select_related=['country'],
             fields=[F('name', 'Название', required=True, searchable=True, hint='Бренд или ателье'),
                     F('country', 'Страна', 'ref', ref_directory='countries', filterable=True),
                     F('website', 'Сайт'), CODE]),
    # ---------------- Контрагенты ----------------
    DictSpec(
        'clients', m.Client, 'Клиенты', 'counterparty', '👰', order=1, display_field='full_name',
        search=['full_name', 'phone_digits', 'instagram', 'whatsapp'], ordering=['full_name'],
        import_keys=['iin', 'phone', 'code'], tabs=['history'],
        fields=[
            F('full_name', 'ФИО', required=True, searchable=True),
            F('iin', 'ИИН', 'iin_bin', searchable=True,
              hint='Необязателен при первом контакте, обязателен при договоре'),
            F('phone', 'Телефон', 'phone', required=True, searchable=True, hint='+7 XXX XXX XX XX'),
            F('whatsapp', 'WhatsApp', show_in_list=False),
            F('instagram', 'Instagram', show_in_list=False, searchable=True),
            F('city', 'Город', hint='Для доставки', filterable=True),
            F('source', 'Источник', 'choice', options=choices(m.CLIENT_SOURCE_CHOICES), filterable=True),
            F('doc_type', 'Тип документа', 'choice', options=choices(m.DOC_TYPE_CHOICES), group='Документ',
              show_in_list=False),
            F('doc_number', 'Номер документа', group='Документ', show_in_list=False),
            F('doc_issued_at', 'Дата выдачи', 'date', group='Документ', show_in_list=False),
            F('pd_consent', 'Согласие на обработку персональных данных', 'bool', group='Документ',
              show_in_list=False, hint='Требование закона РК о персональных данных'),
            F('pd_consent_at', 'Дата согласия', 'datetime', group='Документ', show_in_list=False),
            F('note', 'Примечание', 'text', show_in_list=False),
            CODE,
        ]),
    DictSpec(
        'counterparties', m.Counterparty, 'Контрагенты', 'counterparty', '🤝', order=2,
        search=['name', 'bin_iin', 'contact_person', 'phone'], select_related=['country'],
        import_keys=['bin_iin', 'code', 'name'], tabs=['history'],
        fields=[
            F('name', 'Наименование', required=True, searchable=True),
            F('bin_iin', 'ИИН / БИН', 'iin_bin', searchable=True),
            F('kind', 'Тип', 'choice', required=True, options=choices(m.COUNTERPARTY_KIND_CHOICES), filterable=True),
            F('roles', 'Роли', 'choice', multiple=True, required=True,
              options=choices(m.COUNTERPARTY_ROLE_CHOICES), filterable=True),
            F('country', 'Страна', 'ref', ref_directory='countries', show_in_list=False),
            F('city', 'Город', show_in_list=False),
            F('address', 'Адрес', show_in_list=False),
            F('phone', 'Телефон', 'phone'),
            F('email', 'Email', 'email', show_in_list=False),
            F('contact_person', 'Контактное лицо', searchable=True),
            F('bank', 'Банк', group='Реквизиты', show_in_list=False),
            F('iban', 'IBAN', group='Реквизиты', show_in_list=False),
            F('note', 'Примечание', 'text', show_in_list=False),
            CODE,
        ]),
    # ---------------- Финансы ----------------
    DictSpec('accounts', m.Account, 'Счета', 'finance', '📒', order=1, hierarchical=True,
             select_related=['parent'], ordering=['order', 'name'],
             fields=[F('name', 'Наименование', required=True, searchable=True),
                     F('parent', 'Группа', 'ref', ref_directory='accounts'),
                     F('pnl', 'ОПиУ', 'choice', required=True, options=choices(m.PNL_CHOICES), filterable=True),
                     F('cashflow', 'ДДС', 'choice', required=True, options=choices(m.CASHFLOW_CHOICES),
                       filterable=True),
                     F('func_area', 'Функциональная сфера', 'choice', options=choices(m.FUNC_AREA_CHOICES),
                       filterable=True),
                     ORDER, CODE]),
    DictSpec('deposit_options', m.DepositOption, 'Варианты залога', 'finance', '🔒', order=2,
             ordering=['kind', 'value'],
             fields=[F('name', 'Название', required=True, searchable=True),
                     F('kind', 'Вид', 'choice', required=True, options=choices(m.DepositOption.KIND_CHOICES)),
                     F('value', 'Процент или сумма', 'decimal', required=True), CODE]),
    # ---------------- Общие ----------------
    DictSpec('salons', m.Salon, 'Салоны', 'common', '🏬', order=1,
             fields=[F('name', 'Название', required=True, searchable=True), F('address', 'Адрес'),
                     F('phone', 'Телефон', 'phone'), CODE]),
    DictSpec('countries', m.Country, 'Страны', 'common', '🌍', order=2, search=['name', 'iso_code'],
             import_keys=['iso_code', 'name'],
             fields=[F('iso_code', 'Код ISO', required=True, searchable=True, validation={'mask': r'^[A-Z]{2}$'}),
                     F('name', 'Название', required=True, searchable=True)]),
    DictSpec('stages', m.Stage, 'Стадии', 'common', '🔄', order=3, ordering=['order'],
             fields=[F('name', 'Название', required=True, searchable=True),
                     F('duration_minutes', 'Длительность по умолчанию, мин', 'integer'),
                     F('duration_max_minutes', 'Длительность максимум, мин', 'integer', show_in_list=False),
                     F('is_available', 'Свободен (примерка, выдача)', 'bool'),
                     F('is_optional', 'Необязательная', 'bool'),
                     F('is_terminal', 'Выбытие из цикла', 'bool', show_in_list=False),
                     F('system_key', 'Системный ключ', readonly=True, show_in_list=False),
                     ORDER, CODE]),
    DictSpec('photo_types', m.PhotoType, 'Типы фото', 'common', '📷', order=4, ordering=['order', 'name'],
             fields=[F('name', 'Название', required=True, searchable=True), ORDER, CODE]),
    DictSpec('defect_types', m.DefectType, 'Типы дефектов', 'common', '🧵', order=5,
             fields=[F('name', 'Название', required=True, searchable=True),
                     F('requires_restoration', 'Требует реставрации', 'bool', default=True), CODE]),
]

REGISTRY = {s.code: s for s in SPECS}
MODEL_TO_CODE = {s.model: s.code for s in SPECS}

# Группы справочников для матрицы прав по умолчанию (§6)
PRODUCT_CORE = {'models', 'items', 'kits'}
PRODUCT_CLASSIFIERS = {'events', 'styles', 'sizes', 'colors', 'manufacturers'}
ORG_SETTINGS_DICTS = {'categories'}
COMMON = {'salons', 'countries', 'stages', 'photo_types', 'defect_types'}

# Поля цен (продавцу — только просмотр) и закупки (продавцу — скрыто)
PRICE_FIELDS = {
    'models': ['rent_price', 'min_rent_price', 'sale_price'],
    'items': ['rent_price_override', 'sale_price_override'],
    'kits': ['price'],
}
PURCHASE_FIELDS = {'items': ['cost', 'supplier']}


def get_spec(code) -> Optional[DictSpec]:
    return REGISTRY.get(code)
