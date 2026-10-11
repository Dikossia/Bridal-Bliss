"""
Модели модуля «Мастер-данные» (ТЗ §4).

Принцип (§4.1):
  • системные справочники — обычные Django-модели с явными полями;
  • в каждой системной модели есть поле `extra` (JSONB) для полей, которые
    администратор добавляет через «Структуру» без миграций (МД-10);
  • пользовательские справочники — универсальные таблицы Directory /
    DirectoryField / DirectoryRecord;
  • все записи содержат id (UUID), organization, code, is_active (архив),
    created_by/at, updated_by/at. Физического удаления записей, на которые
    есть ссылки, нет (on_delete=PROTECT + проверка в API, МД-21).
"""
import uuid
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q

from accounts.models import Organization

from .crypto import EncryptedCharField, blind_hash
from .validators import mask_tail, phone_digits

USER = settings.AUTH_USER_MODEL


def org_code_unique(name):
    """Код записи уникален в организации (пустой код допускается многократно)."""
    return models.UniqueConstraint(
        fields=['organization', 'code'], condition=~Q(code=''), name=f'md_{name}_org_code_uniq')


class OrgModel(models.Model):
    """Базовые поля любой записи мастер-данных (§4.1)."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='+')
    code = models.CharField('Код', max_length=64, blank=True, default='')
    is_active = models.BooleanField('Активна (не в архиве)', default=True, db_index=True)
    extra = models.JSONField('Дополнительные поля', default=dict, blank=True)
    created_by = models.ForeignKey(USER, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_by = models.ForeignKey(USER, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    updated_at = models.DateTimeField(auto_now=True)

    # Ключ справочника в реестре (/api/md/<DICT>/...). Задаётся у потомков.
    DICT = ''

    class Meta:
        abstract = True

    def __str__(self):
        return getattr(self, 'name', None) or self.code or str(self.id)


# ============================================================
# Классификаторы товара
# ============================================================
OPERATION_RENT = 'rent'
OPERATION_SALE = 'sale'
OPERATION_BOTH = 'both'
OPERATION_CHOICES = [
    (OPERATION_RENT, 'Аренда'),
    (OPERATION_SALE, 'Продажа'),
    (OPERATION_BOTH, 'Аренда и продажа'),
]

SECTION_CHOICES = [
    ('', '— (всегда включён)'),
    ('uzatu', 'Ұзату'),
    ('shoes', 'Обувь'),
]


class Country(OrgModel):
    DICT = 'countries'
    iso_code = models.CharField('Код ISO', max_length=2)
    name = models.CharField('Название', max_length=100)

    class Meta:
        db_table = 'md_country'
        ordering = ['name']
        constraints = [
            org_code_unique('country'),
            models.UniqueConstraint(fields=['organization', 'iso_code'], name='md_country_iso_uniq'),
        ]


class Category(OrgModel):
    """Дерево категорий товаров (§4.6). Глубина до 3 уровней; модель
    привязывается только к конечной категории. Пустые поля наследуются
    от родителя (префикс, операции, обязательность размера)."""
    DICT = 'categories'
    MAX_DEPTH = 3

    name = models.CharField('Название', max_length=120)
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.PROTECT,
                               related_name='children', verbose_name='Родитель')
    article_prefix = models.CharField('Префикс артикула', max_length=10, blank=True)
    model_mask = models.CharField('Маска артикула модели', max_length=60, blank=True,
                                  help_text='Токены {PREFIX}, {COUNTRY}, {SEQ:3}. По умолчанию {PREFIX}-{SEQ:3}')
    item_mask = models.CharField('Маска артикула экземпляра', max_length=60, blank=True,
                                 help_text='Токены {ARTICLE}, {SIZE}. По умолчанию {ARTICLE}-{SIZE}')
    operations = models.CharField('Операции по умолчанию', max_length=10, choices=OPERATION_CHOICES, blank=True)
    size_required = models.BooleanField('Размер обязателен', null=True, blank=True)
    section = models.CharField('Раздел', max_length=20, choices=SECTION_CHOICES, blank=True)
    is_enabled = models.BooleanField('Включена', default=True)
    order = models.IntegerField('Порядок', default=0)

    class Meta:
        db_table = 'md_category'
        ordering = ['order', 'name']
        constraints = [org_code_unique('category')]

    # ---- дерево ----
    def ancestors(self):
        res, node, guard = [], self.parent, 0
        while node is not None and guard < 10:
            res.append(node)
            node, guard = node.parent, guard + 1
        return res

    @property
    def depth(self):
        return len(self.ancestors()) + 1

    def path_name(self):
        return ' / '.join([a.name for a in reversed(self.ancestors())] + [self.name])

    def is_leaf(self):
        return not self.children.filter(is_active=True).exists()

    def _inherit(self, attr):
        for node in [self] + self.ancestors():
            v = getattr(node, attr)
            if v not in (None, ''):
                return v
        return None

    def effective_prefix(self):
        return self._inherit('article_prefix') or ''

    def effective_operations(self):
        return self._inherit('operations') or OPERATION_BOTH

    def effective_size_required(self):
        return bool(self._inherit('size_required'))

    def effective_model_mask(self):
        return self._inherit('model_mask') or '{PREFIX}-{SEQ:3}'

    def effective_item_mask(self):
        return self._inherit('item_mask') or '{ARTICLE}-{SIZE}'

    def effective_section(self):
        return self._inherit('section') or ''

    def is_selectable(self, org=None):
        """Видна ли категория в выборе: активна, включена, её раздел включён
        и все предки тоже включены (МД-6)."""
        org = org or self.organization
        for node in [self] + self.ancestors():
            if not node.is_active or not node.is_enabled:
                return False
            if node.section and not org.section_enabled(node.section):
                return False
        return True

    def subtree_ids(self):
        """id категории и всех потомков (для фильтра «с подкатегориями», МД-14)."""
        ids, frontier = [self.id], [self.id]
        while frontier:
            frontier = list(Category.objects.filter(parent_id__in=frontier).values_list('id', flat=True))
            ids.extend(frontier)
        return ids


class Event(OrgModel):
    DICT = 'events'
    name = models.CharField('Название', max_length=100)
    order = models.IntegerField('Порядок', default=0)

    class Meta:
        db_table = 'md_event'
        ordering = ['order', 'name']
        constraints = [org_code_unique('event')]


class Style(OrgModel):
    """Вид (стиль) — множественный признак модели. У вида задаётся список
    категорий, где он применим (§4.6)."""
    DICT = 'styles'
    name = models.CharField('Название', max_length=100)
    categories = models.ManyToManyField(Category, blank=True, related_name='styles',
                                        verbose_name='Применимые категории')
    order = models.IntegerField('Порядок', default=0)

    class Meta:
        db_table = 'md_style'
        ordering = ['order', 'name']
        constraints = [org_code_unique('style')]

    def applicable_to(self, category):
        cat_ids = set(self.categories.values_list('id', flat=True))
        if not cat_ids:
            return True
        chain = [category] + category.ancestors()
        return any(c.id in cat_ids for c in chain)


SIZE_SYSTEMS = [('RU', 'RU'), ('EU', 'EU'), ('TR', 'TR'), ('INT', 'INT')]


class Size(OrgModel):
    DICT = 'sizes'
    system = models.CharField('Система', max_length=5, choices=SIZE_SYSTEMS, default='RU')
    value = models.CharField('Значение', max_length=20)
    order = models.IntegerField('Порядок', default=0)

    class Meta:
        db_table = 'md_size'
        ordering = ['system', 'order', 'value']
        constraints = [
            org_code_unique('size'),
            models.UniqueConstraint(fields=['organization', 'system', 'value'], name='md_size_value_uniq'),
        ]

    def __str__(self):
        return self.value if self.system == 'RU' else f'{self.value} {self.system}'


class Color(OrgModel):
    DICT = 'colors'
    name = models.CharField('Название', max_length=60)
    hex = models.CharField('HEX', max_length=7, blank=True)

    class Meta:
        db_table = 'md_color'
        ordering = ['name']
        constraints = [org_code_unique('color')]


class Manufacturer(OrgModel):
    DICT = 'manufacturers'
    name = models.CharField('Название', max_length=150)
    country = models.ForeignKey(Country, null=True, blank=True, on_delete=models.PROTECT,
                                related_name='manufacturers', verbose_name='Страна')
    website = models.CharField('Сайт', max_length=200, blank=True)

    class Meta:
        db_table = 'md_manufacturer'
        ordering = ['name']
        constraints = [org_code_unique('manufacturer')]


class PhotoType(OrgModel):
    DICT = 'photo_types'
    name = models.CharField('Название', max_length=60)
    order = models.IntegerField('Порядок', default=0)

    class Meta:
        db_table = 'md_photo_type'
        ordering = ['order', 'name']
        constraints = [org_code_unique('photo_type')]


class DefectType(OrgModel):
    DICT = 'defect_types'
    name = models.CharField('Название', max_length=100)
    requires_restoration = models.BooleanField('Требует реставрации', default=True)

    class Meta:
        db_table = 'md_defect_type'
        ordering = ['name']
        constraints = [org_code_unique('defect_type')]


class Stage(OrgModel):
    """Стадии жизненного цикла экземпляра (§4.9). Логику переходов задаёт
    будущий модуль операций; здесь — длительности и «свободен на стадии»."""
    DICT = 'stages'
    name = models.CharField('Название', max_length=100)
    system_key = models.CharField('Системный ключ', max_length=40, blank=True,
                                  help_text='Используется логикой других модулей, не меняйте')
    duration_minutes = models.PositiveIntegerField('Длительность по умолчанию, мин', null=True, blank=True)
    duration_max_minutes = models.PositiveIntegerField('Длительность максимум, мин', null=True, blank=True)
    is_available = models.BooleanField('Экземпляр свободен (примерка, выдача)', default=False)
    is_optional = models.BooleanField('Необязательная стадия', default=False)
    is_terminal = models.BooleanField('Выбытие из цикла', default=False)
    order = models.IntegerField('Порядок', default=0)

    class Meta:
        db_table = 'md_stage'
        ordering = ['order']
        constraints = [org_code_unique('stage')]


class Salon(OrgModel):
    DICT = 'salons'
    name = models.CharField('Название', max_length=120)
    address = models.CharField('Адрес', max_length=255, blank=True)
    phone = models.CharField('Телефон', max_length=20, blank=True)

    class Meta:
        db_table = 'md_salon'
        ordering = ['name']
        constraints = [org_code_unique('salon')]


# ============================================================
# Контрагенты (§4.7)
# ============================================================
DOC_TYPE_CHOICES = [
    ('id_card', 'Удостоверение личности'),
    ('passport', 'Паспорт'),
    ('other', 'Другой документ'),
]
CLIENT_SOURCE_CHOICES = [
    ('instagram', 'Instagram'),
    ('whatsapp', 'WhatsApp'),
    ('referral', 'Рекомендация'),
    ('walk_in', 'Проходил мимо'),
    ('other', 'Другое'),
]


class Client(OrgModel):
    """Клиенты — физлица-арендаторы и покупатели. ИИН и номер документа
    хранятся зашифрованными; для уникальности и поиска — HMAC-хеш (§8)."""
    DICT = 'clients'
    full_name = models.CharField('ФИО', max_length=200)
    iin = EncryptedCharField('ИИН', blank=True, default='')
    iin_hash = models.CharField(max_length=64, blank=True, default='', db_index=True, editable=False)
    iin_last4 = models.CharField(max_length=4, blank=True, default='', editable=False)
    doc_type = models.CharField('Тип документа', max_length=20, choices=DOC_TYPE_CHOICES, blank=True)
    doc_number = EncryptedCharField('Номер документа', blank=True, default='')
    doc_last4 = models.CharField(max_length=4, blank=True, default='', editable=False)
    doc_issued_at = models.DateField('Дата выдачи документа', null=True, blank=True)
    phone = models.CharField('Телефон', max_length=20)
    phone_digits = models.CharField(max_length=16, blank=True, default='', db_index=True, editable=False)
    whatsapp = models.CharField('WhatsApp', max_length=40, blank=True)
    instagram = models.CharField('Instagram', max_length=60, blank=True)
    city = models.CharField('Город', max_length=80, blank=True)
    source = models.CharField('Источник', max_length=20, choices=CLIENT_SOURCE_CHOICES, blank=True)
    pd_consent = models.BooleanField('Согласие на обработку ПДн', default=False)
    pd_consent_at = models.DateTimeField('Дата согласия', null=True, blank=True)
    note = models.TextField('Примечание', blank=True)

    class Meta:
        db_table = 'md_client'
        ordering = ['full_name']
        constraints = [
            org_code_unique('client'),
            models.UniqueConstraint(fields=['organization', 'iin_hash'], condition=~Q(iin_hash=''),
                                    name='md_client_iin_uniq'),
        ]

    def __str__(self):
        return self.full_name

    def save(self, *args, **kwargs):
        self.iin_hash = blind_hash(self.iin) if self.iin else ''
        self.iin_last4 = (self.iin or '')[-4:]
        self.doc_last4 = (self.doc_number or '')[-4:]
        self.phone_digits = phone_digits(self.phone)
        super().save(*args, **kwargs)

    @property
    def iin_masked(self):
        return mask_tail(('0' * 8 + self.iin_last4) if self.iin_last4 else '')


COUNTERPARTY_KIND_CHOICES = [
    ('too', 'ТОО'),
    ('ip', 'ИП'),
    ('individual', 'Физлицо'),
    ('foreign', 'Иностранная компания'),
]
COUNTERPARTY_ROLE_CHOICES = [
    ('dress_supplier', 'Поставщик платьев'),
    ('atelier', 'Ателье / швея'),
    ('embroidery', 'Вышивка'),
    ('fabric', 'Ткани и фурнитура'),
    ('dry_cleaning', 'Химчистка'),
    ('restorer', 'Реставратор'),
    ('wholesale_buyer', 'Оптовый покупатель б/у'),
    ('photo_crew', 'Фотограф / модель / визажист'),
]


class Counterparty(OrgModel):
    """Контрагенты — юрлица, ИП и физлица-исполнители (§4.7)."""
    DICT = 'counterparties'
    bin_iin = models.CharField('ИИН / БИН', max_length=12, blank=True)
    name = models.CharField('Наименование', max_length=200)
    kind = models.CharField('Тип', max_length=20, choices=COUNTERPARTY_KIND_CHOICES)
    roles = models.JSONField('Роли', default=list, blank=True)
    country = models.ForeignKey(Country, null=True, blank=True, on_delete=models.PROTECT,
                                related_name='counterparties', verbose_name='Страна')
    city = models.CharField('Город', max_length=80, blank=True)
    address = models.CharField('Адрес', max_length=255, blank=True)
    phone = models.CharField('Телефон', max_length=40, blank=True)
    email = models.CharField('Email', max_length=120, blank=True)
    contact_person = models.CharField('Контактное лицо', max_length=120, blank=True)
    bank = models.CharField('Банк', max_length=120, blank=True)
    iban = models.CharField('IBAN', max_length=34, blank=True)
    note = models.TextField('Примечание', blank=True)

    class Meta:
        db_table = 'md_counterparty'
        ordering = ['name']
        constraints = [org_code_unique('counterparty')]


# ============================================================
# Финансы (§4.8)
# ============================================================
class DepositOption(OrgModel):
    """Варианты залога: размер залога относится к сделке, а не к клиенту."""
    DICT = 'deposit_options'
    KIND_CHOICES = [('percent', 'Процент'), ('amount', 'Сумма')]
    name = models.CharField('Название', max_length=60)
    kind = models.CharField('Вид', max_length=10, choices=KIND_CHOICES, default='percent')
    value = models.DecimalField('Значение', max_digits=12, decimal_places=2,
                                validators=[MinValueValidator(Decimal('0'))])

    class Meta:
        db_table = 'md_deposit_option'
        ordering = ['kind', 'value']
        constraints = [org_code_unique('deposit_option')]


PNL_CHOICES = [('income', 'Доход'), ('expense', 'Расход'), ('none', 'Не влияет')]
CASHFLOW_CHOICES = [('inflow', 'Поступление'), ('outflow', 'Выплата'), ('none', 'Не влияет')]
FUNC_AREA_CHOICES = [
    ('cogs', 'Себестоимость продаж'),
    ('cost_of_services', 'Себестоимость услуг'),
    ('selling', 'Расходы на продажу и маркетинг'),
    ('logistics', 'Логистические расходы'),
    ('admin', 'Административные расходы'),
]


class Account(OrgModel):
    """Счёт (статья доходов/расходов) — иерархический справочник с тремя
    классификаторами: ОПиУ, ДДС, функциональная сфера."""
    DICT = 'accounts'
    name = models.CharField('Наименование', max_length=150)
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.PROTECT,
                               related_name='children', verbose_name='Группа')
    pnl = models.CharField('ОПиУ', max_length=10, choices=PNL_CHOICES, default='none')
    cashflow = models.CharField('ДДС', max_length=10, choices=CASHFLOW_CHOICES, default='none')
    func_area = models.CharField('Функциональная сфера', max_length=20, choices=FUNC_AREA_CHOICES, blank=True)
    order = models.IntegerField('Порядок', default=0)

    class Meta:
        db_table = 'md_account'
        ordering = ['order', 'name']
        constraints = [org_code_unique('account')]


# ============================================================
# Товар: модель → экземпляр → комплект (§4.3–4.5)
# ============================================================
ACQUISITION_CHOICES = [('purchase', 'Закуп'), ('tailoring', 'Пошив')]


class ProductModel(OrgModel):
    """Номенклатура (модель) — описание товара, не физическая вещь."""
    DICT = 'models'
    article = models.CharField('Артикул модели', max_length=40)
    name = models.CharField('Наименование', max_length=200)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name='models',
                                 verbose_name='Категория')
    events = models.ManyToManyField(Event, related_name='models', verbose_name='Мероприятия')
    styles = models.ManyToManyField(Style, blank=True, related_name='models', verbose_name='Виды (стили)')
    manufacturer = models.ForeignKey(Manufacturer, null=True, blank=True, on_delete=models.PROTECT,
                                     related_name='models', verbose_name='Производитель')
    country = models.ForeignKey(Country, null=True, blank=True, on_delete=models.PROTECT,
                                related_name='models', verbose_name='Страна происхождения')
    manufacturer_article = models.CharField('Артикул производителя', max_length=60, blank=True)
    acquisition = models.CharField('Способ поступления', max_length=10, choices=ACQUISITION_CHOICES,
                                   default='purchase')
    operations = models.CharField('Операции', max_length=10, choices=OPERATION_CHOICES)
    color = models.ForeignKey(Color, null=True, blank=True, on_delete=models.PROTECT,
                              related_name='models', verbose_name='Цвет')
    rent_price = models.DecimalField('Цена аренды, ₸', max_digits=12, decimal_places=2, null=True, blank=True)
    min_rent_price = models.DecimalField('Минимальная цена аренды, ₸', max_digits=12, decimal_places=2,
                                         null=True, blank=True)
    sale_price = models.DecimalField('Цена продажи, ₸', max_digits=12, decimal_places=2, null=True, blank=True)
    resource = models.PositiveIntegerField('Ресурс, аренд', default=10)
    return_check_details = models.JSONField('Детали для проверки при возврате', default=list, blank=True)
    description = models.TextField('Описание', blank=True)
    show_in_catalog = models.BooleanField('Показывать в каталоге', default=False)

    class Meta:
        db_table = 'md_product_model'
        ordering = ['article']
        constraints = [
            org_code_unique('product_model'),
            models.UniqueConstraint(fields=['organization', 'article'], name='md_model_article_uniq'),
        ]

    def __str__(self):
        return f'{self.article} {self.name}'

    def save(self, *args, **kwargs):
        self.code = self.article
        super().save(*args, **kwargs)

    @property
    def main_photo(self):
        return self.photos.order_by('-is_main', 'order', 'created_at').first()


CONDITION_CHOICES = [('new', 'Новое'), ('used', 'Б/у')]
ITEM_STATUS_CHOICES = [
    ('active', 'Активен'),
    ('sold', 'Продан'),
    ('written_off', 'Списан'),
    ('disassembled', 'Разобран на детали'),
]


class Item(OrgModel):
    """Экземпляр — конкретная физическая вещь с биркой. Именно экземпляр
    бронируется, сдаётся, продаётся и списывается."""
    DICT = 'items'
    tag = models.CharField('Бирка (инвентарный номер)', max_length=20)
    model = models.ForeignKey(ProductModel, on_delete=models.PROTECT, related_name='items',
                              verbose_name='Модель')
    size = models.ForeignKey(Size, null=True, blank=True, on_delete=models.PROTECT, related_name='items',
                             verbose_name='Размер')
    length_cm = models.DecimalField('Длина / рост, см', max_digits=6, decimal_places=1, null=True, blank=True)
    barcode = models.CharField('Штрихкод', max_length=64, blank=True, db_index=True)
    salon = models.ForeignKey(Salon, on_delete=models.PROTECT, related_name='items', verbose_name='Салон')
    condition = models.CharField('Состояние', max_length=10, choices=CONDITION_CHOICES, default='new')
    status = models.CharField('Статус', max_length=20, choices=ITEM_STATUS_CHOICES, default='active')
    stage = models.ForeignKey(Stage, on_delete=models.PROTECT, related_name='items', verbose_name='Текущая стадия')
    received_at = models.DateField('Дата поступления')
    supplier = models.ForeignKey(Counterparty, null=True, blank=True, on_delete=models.PROTECT,
                                 related_name='supplied_items', verbose_name='Поставщик')
    cost = models.DecimalField('Стоимость поступления, ₸', max_digits=12, decimal_places=2, null=True, blank=True)
    rent_count = models.PositiveIntegerField('Выдано в аренду, раз', default=0)
    rent_price_override = models.DecimalField('Индивидуальная цена аренды, ₸', max_digits=12, decimal_places=2,
                                              null=True, blank=True)
    sale_price_override = models.DecimalField('Индивидуальная цена продажи, ₸', max_digits=12, decimal_places=2,
                                              null=True, blank=True)
    note = models.TextField('Примечание', blank=True)

    class Meta:
        db_table = 'md_item'
        ordering = ['tag']
        constraints = [
            org_code_unique('item'),
            models.UniqueConstraint(fields=['organization', 'tag'], name='md_item_tag_uniq'),
        ]

    def __str__(self):
        return f'{self.tag} · {self.article}'

    def save(self, *args, **kwargs):
        self.code = self.tag
        super().save(*args, **kwargs)

    @property
    def article(self):
        """Артикул экземпляра = артикул модели + размер (СВ-117-44), по маске категории."""
        from .articles import item_article
        return item_article(self)

    @property
    def active_kit_link(self):
        return self.kit_links.filter(kit_active=True).select_related('kit').first()


KIT_ROLE_CHOICES = [
    ('base', 'База'),
    ('dress', 'Платье'),
    ('kamzol', 'Қамзол'),
    ('takiya', 'Тақия'),
    ('saukele', 'Сәукеле'),
    ('corset', 'Корсет'),
    ('shapan', 'Шапан'),
    ('veil', 'Фата'),
    ('bolero', 'Болеро'),
    ('other', 'Прочее'),
]


class Kit(OrgModel):
    """Комплект — набор экземпляров, выдаваемых вместе (§4.5)."""
    DICT = 'kits'
    name = models.CharField('Наименование', max_length=200)
    main_item = models.ForeignKey(Item, null=True, blank=True, on_delete=models.PROTECT, related_name='+',
                                  verbose_name='Основной экземпляр')
    price = models.DecimalField('Цена комплекта, ₸', max_digits=12, decimal_places=2, null=True, blank=True)
    can_split = models.BooleanField('Можно выдавать по частям', default=True)

    class Meta:
        db_table = 'md_kit'
        ordering = ['code']
        constraints = [org_code_unique('kit')]

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Экземпляр может входить только в один АКТИВНЫЙ комплект: признак
        # активности дублируется в строки состава для уникального индекса.
        self.components.exclude(kit_active=self.is_active).update(kit_active=self.is_active)


class KitItem(models.Model):
    """Строка состава комплекта."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='+')
    kit = models.ForeignKey(Kit, on_delete=models.CASCADE, related_name='components')
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name='kit_links', verbose_name='Экземпляр')
    role = models.CharField('Роль', max_length=20, choices=KIT_ROLE_CHOICES, default='other')
    order = models.IntegerField(default=0)
    kit_active = models.BooleanField(default=True, editable=False)

    class Meta:
        db_table = 'md_kit_item'
        ordering = ['order']
        constraints = [
            models.UniqueConstraint(fields=['kit', 'item'], name='md_kit_item_uniq'),
            models.UniqueConstraint(fields=['item'], condition=Q(kit_active=True), name='md_item_one_active_kit'),
        ]


def photo_upload_to(instance, filename):
    return f'md/{instance.organization_id}/photos/{uuid.uuid4().hex}_{filename[-80:]}'


class Photo(models.Model):
    """Фото модели, экземпляра или записи пользовательского справочника (МД-19)."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='+')
    product_model = models.ForeignKey(ProductModel, null=True, blank=True, on_delete=models.CASCADE,
                                      related_name='photos')
    item = models.ForeignKey(Item, null=True, blank=True, on_delete=models.CASCADE, related_name='photos')
    record = models.ForeignKey('DirectoryRecord', null=True, blank=True, on_delete=models.CASCADE,
                               related_name='photos')
    file = models.FileField(upload_to=photo_upload_to, max_length=255)
    thumb_300 = models.FileField(upload_to=photo_upload_to, max_length=255, blank=True)
    thumb_1200 = models.FileField(upload_to=photo_upload_to, max_length=255, blank=True)
    photo_type = models.ForeignKey(PhotoType, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    order = models.IntegerField(default=0)
    is_main = models.BooleanField(default=False)
    original_name = models.CharField(max_length=255, blank=True)
    size_bytes = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(USER, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'md_photo'
        ordering = ['-is_main', 'order', 'created_at']


# ============================================================
# Пользовательские справочники и структура (§4.1, МД-1…12)
# ============================================================
MENU_GROUP_CHOICES = [
    ('product', 'Товар'),
    ('counterparty', 'Контрагенты'),
    ('finance', 'Финансы'),
    ('common', 'Общие'),
    ('custom', 'Пользовательские справочники'),
]

FIELD_TYPE_CHOICES = [
    ('string', 'Строка'),
    ('text', 'Многострочный текст'),
    ('integer', 'Целое'),
    ('decimal', 'Дробное'),
    ('money', 'Деньги (₸)'),
    ('percent', 'Процент'),
    ('date', 'Дата'),
    ('datetime', 'Дата и время'),
    ('bool', 'Да/нет'),
    ('choice', 'Список значений'),
    ('ref', 'Ссылка на справочник'),
    ('phone', 'Телефон'),
    ('email', 'Email'),
    ('iin_bin', 'ИИН/БИН'),
    ('file', 'Файл'),
    ('photo', 'Фото (галерея)'),
    ('computed', 'Вычисляемое'),
]


class Directory(OrgModel):
    """Описание справочника. Строки есть и для системных справочников
    (is_system=True) — в них хранятся настройки меню и доп. поля (МД-10)."""
    name = models.CharField('Название', max_length=120)
    description = models.TextField('Описание', blank=True)
    menu_group = models.CharField('Группа меню', max_length=20, choices=MENU_GROUP_CHOICES, default='custom')
    icon = models.CharField('Иконка', max_length=8, blank=True, default='📁')
    is_system = models.BooleanField('Системный', default=False)
    is_hierarchical = models.BooleanField('Иерархический', default=False)
    display_field = models.CharField('Поле-представление', max_length=63, blank=True, default='name')
    supports_photo = models.BooleanField('Поддержка фото', default=False)
    supports_archive = models.BooleanField('Поддержка архива', default=True)
    menu_enabled = models.BooleanField('Показывать в меню', default=True)
    order = models.IntegerField('Порядок', default=0)

    class Meta:
        db_table = 'md_directory'
        ordering = ['menu_group', 'order', 'name']
        constraints = [org_code_unique('directory')]

    def __str__(self):
        return self.name


class DirectoryField(models.Model):
    """Описание поля справочника (МД-7…9). Для системных справочников
    системные поля (is_system=True) зеркалят колонки модели: их можно
    переименовать и переставить, но нельзя удалить или сменить тип."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='+')
    directory = models.ForeignKey(Directory, on_delete=models.CASCADE, related_name='fields')
    code = models.CharField('Код', max_length=63)
    name = models.CharField('Название', max_length=120)
    type = models.CharField('Тип', max_length=20, choices=FIELD_TYPE_CHOICES, default='string')
    is_system = models.BooleanField(default=False)
    required = models.BooleanField('Обязательное', default=False)
    unique = models.BooleanField('Уникальное', default=False)
    default = models.JSONField('Значение по умолчанию', null=True, blank=True)
    hint = models.CharField('Подсказка', max_length=255, blank=True)
    order = models.IntegerField('Порядок', default=0)
    group = models.CharField('Группа (вкладка карточки)', max_length=60, blank=True, default='Основное')
    show_in_list = models.BooleanField('Показывать в списке', default=True)
    searchable = models.BooleanField('Участвует в поиске', default=False)
    filterable = models.BooleanField('Участвует в фильтре', default=False)
    options = models.JSONField('Значения списка', default=list, blank=True)  # [{"value","label"}]
    multiple = models.BooleanField('Несколько значений', default=False)
    ref_directory = models.CharField('Ссылка на справочник (код)', max_length=64, blank=True)
    validation = models.JSONField('Ограничения', default=dict, blank=True)
    # {"min_len","max_len","mask","min","max","ref_filter"}
    readonly = models.BooleanField(default=False)  # вычисляемые системные поля
    is_archived = models.BooleanField('Удалено (значения в архиве)', default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'md_directory_field'
        ordering = ['order', 'created_at']
        constraints = [models.UniqueConstraint(fields=['directory', 'code'], name='md_dir_field_code_uniq')]

    def __str__(self):
        return f'{self.directory.code}.{self.code}'


class DirectoryRecord(OrgModel):
    """Запись пользовательского справочника: данные в JSONB."""
    directory = models.ForeignKey(Directory, on_delete=models.PROTECT, related_name='records')
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.PROTECT, related_name='children')
    data = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = 'md_directory_record'
        ordering = ['created_at']
        constraints = [models.UniqueConstraint(fields=['directory', 'code'], condition=~Q(code=''),
                                               name='md_record_code_uniq')]

    def __str__(self):
        df = self.directory.display_field or 'name'
        return str(self.data.get(df) or self.code or self.id)


# ============================================================
# Журналы, права, настройки пользователя, счётчики
# ============================================================
class AuditLog(models.Model):
    """История изменений записей (МД-22). Хранится не менее 3 лет (§8) —
    очистка старше срока делается командой md_purge_audit."""
    ACTION_CHOICES = [
        ('create', 'Создание'), ('update', 'Изменение'), ('archive', 'Архивирование'),
        ('restore', 'Восстановление'), ('delete', 'Удаление'),
    ]
    id = models.BigAutoField(primary_key=True)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='+')
    entity = models.CharField(max_length=64)            # ключ справочника
    record_id = models.CharField(max_length=36)
    record_repr = models.CharField(max_length=255, blank=True)
    action = models.CharField(max_length=10, choices=ACTION_CHOICES)
    source = models.CharField(max_length=10, default='ui')  # ui | api | import
    user = models.ForeignKey(USER, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    record_owner_id = models.BigIntegerField(null=True, blank=True)  # автор записи (для «своих записей»)
    at = models.DateTimeField(auto_now_add=True, db_index=True)
    changes = models.JSONField(default=list, blank=True)  # [{"field","label","old","new"}]

    class Meta:
        db_table = 'md_audit_log'
        ordering = ['-at', '-id']
        indexes = [models.Index(fields=['organization', 'entity', 'record_id'])]


class StructureLog(models.Model):
    """Журнал изменений структуры справочников (МД-12)."""
    id = models.BigAutoField(primary_key=True)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='+')
    directory_code = models.CharField(max_length=64)
    action = models.CharField(max_length=40)
    details = models.JSONField(default=dict, blank=True)
    user = models.ForeignKey(USER, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'md_structure_log'
        ordering = ['-at', '-id']


class RolePolicy(models.Model):
    """Матрица «роль × справочник × действие» + скрытые и read-only поля (§6)."""
    HISTORY_CHOICES = [('all', 'Все записи'), ('own', 'Свои записи'), ('none', 'Нет')]
    id = models.BigAutoField(primary_key=True)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='+')
    role = models.CharField(max_length=20)
    directory_code = models.CharField(max_length=64)
    can_view = models.BooleanField(default=True)
    can_create = models.BooleanField(default=False)
    can_update = models.BooleanField(default=False)
    can_archive = models.BooleanField(default=False)
    can_import = models.BooleanField(default=False)
    can_export = models.BooleanField(default=False)
    history = models.CharField(max_length=5, choices=HISTORY_CHOICES, default='all')
    hidden_fields = models.JSONField(default=list, blank=True)
    readonly_fields = models.JSONField(default=list, blank=True)

    class Meta:
        db_table = 'md_role_policy'
        constraints = [models.UniqueConstraint(fields=['organization', 'role', 'directory_code'],
                                               name='md_role_policy_uniq')]


class UserPreference(models.Model):
    """Настройки пользователя: колонки и их порядок в списках (МД-13)."""
    id = models.BigAutoField(primary_key=True)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='+')
    user = models.ForeignKey(USER, on_delete=models.CASCADE, related_name='+')
    key = models.CharField(max_length=100)
    value = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = 'md_user_preference'
        constraints = [models.UniqueConstraint(fields=['organization', 'user', 'key'], name='md_user_pref_uniq')]


class Counter(models.Model):
    """Счётчики SEQ — отдельно по каждому префиксу артикула, бирке, комплекту."""
    id = models.BigAutoField(primary_key=True)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='+')
    key = models.CharField(max_length=40)
    value = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'md_counter'
        constraints = [models.UniqueConstraint(fields=['organization', 'key'], name='md_counter_uniq')]


class ImportProfile(models.Model):
    """Сохранённое сопоставление колонок для повторных загрузок (МД-27)."""
    id = models.BigAutoField(primary_key=True)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='+')
    directory_code = models.CharField(max_length=64)
    name = models.CharField(max_length=100)
    mapping = models.JSONField(default=dict)
    created_by = models.ForeignKey(USER, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'md_import_profile'
        constraints = [models.UniqueConstraint(fields=['organization', 'directory_code', 'name'],
                                               name='md_import_profile_uniq')]


def import_upload_to(instance, filename):
    return f'md/{instance.organization_id}/imports/{uuid.uuid4().hex}_{filename[-80:]}'


class ImportJob(models.Model):
    """Загрузка (журнал импорта, МД-32)."""
    STATUS_CHOICES = [
        ('uploaded', 'Файл загружен'), ('previewing', 'Проверка'), ('previewed', 'Проверено'),
        ('running', 'Загрузка'), ('done', 'Выполнено'), ('failed', 'Ошибка'),
    ]
    MODE_CHOICES = [('create', 'Только создание'), ('update', 'Только обновление'),
                    ('upsert', 'Создание и обновление')]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='+')
    directory_code = models.CharField(max_length=64)
    user = models.ForeignKey(USER, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    file = models.FileField(upload_to=import_upload_to, max_length=255)
    original_name = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default='uploaded')
    mode = models.CharField(max_length=10, choices=MODE_CHOICES, default='create')
    key_field = models.CharField(max_length=63, blank=True)
    mapping = models.JSONField(default=dict, blank=True)     # {"Заголовок колонки": "field_code"}
    options = models.JSONField(default=dict, blank=True)     # create_missing_refs, only_valid
    headers = models.JSONField(default=list, blank=True)
    total_rows = models.PositiveIntegerField(default=0)
    processed_rows = models.PositiveIntegerField(default=0)
    counts = models.JSONField(default=dict, blank=True)      # create/update/skip/error
    errors = models.JSONField(default=list, blank=True)      # [{"row","column","message"}]
    error_file = models.FileField(upload_to=import_upload_to, max_length=255, blank=True)
    message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'md_import_job'
        ordering = ['-created_at']
