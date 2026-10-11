"""Критерии приёмки модуля (ТЗ §9) — по одному тесту на сценарий."""
import io
import zipfile

from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from accounts.models import Organization
from masterdata import models as m

from .base import MDTestCase


def jpeg_bytes(color=(250, 250, 250)):
    buf = io.BytesIO()
    Image.new('RGB', (1600, 1200), color).save(buf, 'JPEG')
    return buf.getvalue()


class AcceptanceTests(MDTestCase):
    # 1. При регистрации организации создаются системные справочники с наполнением
    def test_01_new_org_gets_system_dictionaries(self):
        org = Organization.objects.create(name='Новый салон')
        self.assertEqual(m.Directory.objects.filter(organization=org, is_system=True).count(), 18)
        self.assertTrue(m.Category.objects.filter(organization=org, name='Свадебные платья', article_prefix='СВ').exists())
        self.assertEqual(m.Category.objects.get(organization=org, name='Қамзол').effective_prefix(), 'КМ')
        self.assertEqual(m.Stage.objects.filter(organization=org).count(), 9)
        self.assertEqual(list(m.DepositOption.objects.filter(organization=org).values_list('value', flat=True)
                              .order_by('value')), [10, 20, 50])
        self.assertTrue(m.Account.objects.filter(organization=org, name='Аренда платьев', pnl='income').exists())
        self.assertEqual(m.Event.objects.filter(organization=org).count(), 7)
        self.assertTrue(m.RolePolicy.objects.filter(organization=org, role='seller', directory_code='models').exists())
        # «Обувь» создана, но раздел выключен
        self.assertFalse(org.section_enabled('shoes'))

    # 2. Выключение «Ұзату» скрывает его категории из выбора, модели не теряются
    def test_02_disable_uzatu_section(self):
        kamzol = self.ok(self.client.post('/api/md/d/models/', {
            'name': 'Қамзол бархатный', 'category': self.cat('Қамзол'), 'events': [self.event('Ұзату')],
            'rent_price': 40000}, format='json'), 201)
        self.assertEqual(kamzol['operations'], 'rent')  # операции по умолчанию из категории
        self.assertTrue(kamzol['article'].startswith('КМ-'))
        opts = self.ok(self.client.get('/api/md/d/categories/options/'))
        self.assertIn('Ұзату / Қамзол', [o['label'] for o in opts])

        self.ok(self.client.patch('/api/md/org/', {'sections': {'uzatu': False}}, format='json'))
        labels = [o['label'] for o in self.ok(self.client.get('/api/md/d/categories/options/'))]
        self.assertNotIn('Ұзату / Қамзол', labels)
        self.assertIn('Свадебные платья', labels)
        # Модель на месте и открывается
        self.ok(self.client.get(f'/api/md/d/models/{kamzol["id"]}/'))
        self.assertEqual(self.client.get('/api/md/d/models/').data['total'], 1)
        # Новую модель в выключенной категории создать нельзя
        r = self.client.post('/api/md/d/models/', {'name': 'X', 'category': self.cat('Қамзол'),
                                                   'events': [self.event('Ұзату')], 'rent_price': 1}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('category', r.data['fields'])
        # Виды, применимые только к выключенным категориям, тоже скрыты — а общие остаются
        styles = [o['label'] for o in self.ok(self.client.get('/api/md/d/styles/options/'))]
        self.assertIn('Королевское', styles)

    # 3. Модель с двумя видами и двумя мероприятиями находится фильтром по каждому
    def test_03_filters_by_styles_and_events(self):
        dress = self.create_dress(styles=[self.style('Королевское'), self.style('Кружевное')],
                                  events=[self.event('Свадьба'), self.event('Выпускной')])
        self.create_dress(name='Другое', styles=[self.style('Рыбка')], events=[self.event('Фотосессия')])
        for key, val in [('styles', self.style('Королевское')), ('styles', self.style('Кружевное')),
                         ('events', self.event('Свадьба')), ('events', self.event('Выпускной'))]:
            res = self.client.get('/api/md/d/models/', {key: val}).data
            self.assertEqual([x['id'] for x in res['data']], [dress['id']], key)
        # вид, неприменимый к категории, не сохраняется (МД-9)
        r = self.client.post('/api/md/d/models/', {
            'name': 'Букет', 'category': self.cat('Букеты'), 'events': [self.event('Свадьба')],
            'styles': [self.style('Рыбка')], 'sale_price': 15000}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('styles', r.data['fields'])

    # 4. СВ-117: экземпляры 42 и 44 одной операцией, артикулы, бирки, PDF
    def test_04_add_items_and_labels(self):
        model = self.create_dress(article='СВ-117')
        r = self.client.post(f'/api/md/d/models/{model["id"]}/add-items/', {
            'sizes': [{'size': self.size('42'), 'qty': 1}, {'size': self.size('44'), 'qty': 1}],
            'salon': self.salon(), 'supplier': self.supplier(), 'received_at': '2026-10-01', 'cost': 400000,
        }, format='json')
        items = self.ok(r, 201)
        self.assertEqual(sorted(i['article'] for i in items), ['СВ-117-42', 'СВ-117-44'])
        tags = [i['tag'] for i in items]
        self.assertEqual(len(set(tags)), 2)
        self.assertTrue(all(len(t) == 6 and t.isdigit() for t in tags))
        self.assertEqual(items[0]['stage__display'], 'В салоне')  # стадия при вводе
        pdf = self.client.get('/api/md/labels/', {'ids': ','.join(i['id'] for i in items)})
        self.assertEqual(pdf.status_code, 200)
        self.assertEqual(pdf['Content-Type'], 'application/pdf')
        self.assertTrue(pdf.content.startswith(b'%PDF'))
        self.assertEqual(pdf.content.count(b'/Type /Page\n') + pdf.content.count(b'/Type /Page '), 2)
        # следующая модель получает следующий номер по префиксу
        nxt = self.create_dress(name='Следующее')
        self.assertEqual(nxt['article'], 'СВ-118')
        # поиск по артикулу экземпляра открывает одну запись
        s = self.ok(self.client.get('/api/md/search/', {'q': 'СВ-117-44'}))
        self.assertEqual(s['single']['dict'], 'items')

    # 5. Комплект ұзату из 5 экземпляров; тот же қамзол во второй комплект — блок
    def test_05_kit_uniqueness(self):
        ids = {}
        for cat, role, size, ops, price in [('База', 'base', '44', 'both', 1), ('Қамзол', 'kamzol', None, 'rent', 0),
                                            ('Тақия', 'takiya', None, 'rent', 0), ('Сәукеле', 'saukele', None, 'rent', 0),
                                            ('Корсет', 'corset', '44', 'rent', 0)]:
            data = {'name': cat, 'category': self.cat(cat), 'events': [self.event('Ұзату')], 'rent_price': 50000,
                    'operations': ops}
            if ops == 'both':
                data['sale_price'] = 500000
            model = self.ok(self.client.post('/api/md/d/models/', data, format='json'), 201)
            ids[role] = self.create_item(model['id'], size)['id']
        kit = self.ok(self.client.post('/api/md/d/kits/', {
            'name': 'Ұзату «Ақ жол»', 'main_item': ids['base'],
            'components': [{'item': i, 'role': r} for r, i in ids.items()]}, format='json'), 201)
        self.assertEqual(len(kit['components']), 5)
        self.assertTrue(kit['code'].startswith('КТ-'))
        self.assertTrue(kit['can_split'])
        r = self.client.post('/api/md/d/kits/', {'name': 'Второй', 'components': [{'item': ids['kamzol'],
                                                                                   'role': 'kamzol'}]}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('уже входит в активный комплект', str(r.data['fields']['components']))
        # после архивации первого комплекта қамзол свободен
        self.ok(self.client.post(f'/api/md/d/kits/{kit["id"]}/archive/'))
        self.ok(self.client.post('/api/md/d/kits/', {'name': 'Второй', 'components': [{'item': ids['kamzol'],
                                                                                       'role': 'kamzol'}]},
                                 format='json'), 201)
        # а восстановить первый теперь нельзя — қамзол занят
        r = self.client.post(f'/api/md/d/kits/{kit["id"]}/restore/')
        self.assertEqual(r.status_code, 400)

    # 6. Фата — только продажа; без цены продажи не сохраняется
    def test_06_veil_sale_only(self):
        base = {'name': 'Фата кружевная', 'category': self.cat('Фата'), 'events': [self.event('Свадьба')],
                'styles': [self.style('Кружевное')]}
        r = self.client.post('/api/md/d/models/', {**base, 'operations': 'rent', 'rent_price': 10000}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('operations', r.data['fields'])
        r = self.client.post('/api/md/d/models/', {**base, 'operations': 'sale'}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('sale_price', r.data['fields'])
        veil = self.ok(self.client.post('/api/md/d/models/', {**base, 'sale_price': 25000}, format='json'), 201)
        self.assertEqual(veil['operations'], 'sale')
        self.assertTrue(veil['article'].startswith('ФТ-'))

    # 7. Мин. цена > базовой не сохраняется; продавец видит цены, не меняет, не видит закупку
    def test_07_prices_and_seller_rights(self):
        r = self.client.post('/api/md/d/models/', {
            'name': 'X', 'category': self.cat('Свадебные платья'), 'events': [self.event('Свадьба')],
            'operations': 'rent', 'rent_price': 100000, 'min_rent_price': 150000}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('min_rent_price', r.data['fields'])
        r = self.client.post('/api/md/d/models/', {
            'name': 'X', 'category': self.cat('Свадебные платья'), 'events': [self.event('Свадьба')],
            'operations': 'rent', 'rent_price': 100000, 'resource': 0}, format='json')
        self.assertIn('resource', r.data['fields'])

        model = self.create_dress()
        item = self.create_item(model['id'], '44', cost=300000)
        seller = self.api(self.make_user('seller@test.kz', 'seller'))
        got = self.ok(seller.get(f'/api/md/d/models/{model["id"]}/'))
        self.assertEqual(float(got['rent_price']), 150000)
        r = seller.patch(f'/api/md/d/models/{model["id"]}/', {'rent_price': 1}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('rent_price', r.data['fields'])
        # остальное продавец менять может
        self.ok(seller.patch(f'/api/md/d/models/{model["id"]}/', {'description': 'Шлейф 2 м'}, format='json'))
        it = self.ok(seller.get(f'/api/md/d/items/{item["id"]}/'))
        self.assertNotIn('cost', it)
        self.assertNotIn('supplier', it)
        meta = self.ok(seller.get('/api/md/d/items/meta/'))
        self.assertNotIn('cost', [f['code'] for f in meta['fields']])
        price_meta = [f for f in self.ok(seller.get('/api/md/d/models/meta/'))['fields'] if f['code'] == 'rent_price']
        self.assertTrue(price_meta[0]['readonly'])
        # продавец создаёт экземпляр без поставщика (поле скрыто) — не блокируется
        self.ok(seller.post('/api/md/d/items/', {'model': model['id'], 'size': self.size('42'),
                                                 'salon': self.salon(), 'cost': 1}, format='json'), 201)
        self.assertIsNone(m.Item.objects.filter(organization=self.org, size__value='42').first().cost)
        # продавцу недоступны импорт, экспорт, архив
        self.assertEqual(seller.get('/api/md/d/models/export/').status_code, 403)
        self.assertEqual(seller.post(f'/api/md/d/models/{model["id"]}/archive/').status_code, 403)

    # 8. Клиент с неверным ИИН не сохраняется; существующий телефон — предупреждение
    def test_08_client_iin_and_duplicates(self):
        r = self.client.post('/api/md/d/clients/', {'full_name': 'Иванова Анна', 'phone': '+7 701 111 22 33',
                                                    'iin': '900101300015'}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('iin', r.data['fields'])
        c = self.ok(self.client.post('/api/md/d/clients/', {'full_name': 'Иванова Анна', 'phone': '87011112233',
                                                            'iin': '900101300017'}, format='json'), 201)
        self.assertEqual(c['phone'], '+77011112233')
        r = self.client.post('/api/md/d/clients/', {'full_name': 'Сәрсенова Әйгерім', 'phone': '+7 (701) 111-22-33'},
                             format='json')
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data['warnings'][0]['field'], 'phone')
        dup = self.ok(self.client.get('/api/md/clients/check-duplicates/', {'phone': '8 701 111 22 33'}))
        self.assertTrue(dup)
        # ИИН уникален
        r = self.client.post('/api/md/d/clients/', {'full_name': 'Другая', 'phone': '+77020000000',
                                                    'iin': '900101300017'}, format='json')
        self.assertIn('iin', r.data['fields'])
        # ИИН зашифрован в БД и маскируется в списке
        from django.db import connection
        with connection.cursor() as cur:
            cur.execute('SELECT iin FROM md_client WHERE id=%s', [c['id']])
            self.assertNotIn('900101300017', cur.fetchone()[0])
        lst = self.client.get('/api/md/d/clients/').data['data']
        self.assertTrue(any(x['iin'] and x['iin'].endswith('0017') and x['iin'].startswith('•') for x in lst))
        # поиск по ИИН и казахским буквам
        self.assertEqual(self.ok(self.client.get('/api/md/search/', {'q': '900101300017'}))['single']['id'], c['id'])
        found = self.client.get('/api/md/d/clients/', {'q': 'әйгерім'}).data['data']
        self.assertEqual(len(found), 1)

    # 9. Пользовательский справочник «Ткани» с 4 полями: вручную и импортом
    def test_09_custom_directory_fabrics(self):
        self.ok(self.client.post('/api/md/directories/', {'code': 'fabrics', 'name': 'Ткани', 'icon': '🧶'},
                                 format='json'), 201)
        for f in [{'code': 'price_m', 'name': 'Цена за метр', 'type': 'money', 'required': True},
                  {'code': 'kind', 'name': 'Вид ткани', 'type': 'choice', 'filterable': True,
                   'options': ['Атлас', 'Фатин', 'Кружево']},
                  {'code': 'country', 'name': 'Страна', 'type': 'ref', 'ref_directory': 'countries'},
                  {'code': 'in_stock', 'name': 'Есть на складе', 'type': 'bool'}]:
            self.ok(self.client.post('/api/md/directories/fabrics/fields/', f, format='json'), 201)
        rec = self.ok(self.client.post('/api/md/d/fabrics/', {
            'name': 'Атлас итальянский', 'price_m': '4 500', 'kind': 'Атлас', 'country': self.get_id(m.Country, iso_code='TR'),
            'in_stock': True}, format='json'), 201)
        self.assertEqual(rec['price_m'], 4500)
        self.assertEqual(rec['country__display'], 'Турция')
        r = self.client.post('/api/md/d/fabrics/', {'name': 'Без цены'}, format='json')
        self.assertIn('price_m', r.data['fields'])
        csv_data = 'Наименование;Цена за метр;Вид ткани;Страна;Есть на складе\n' \
                   'Фатин мягкий;1200;фатин;Китай;да\nКружево шантильи;9800,50;Кружево;TR;нет\n'
        up = self.ok(self.client.post('/api/md/import/upload/', {
            'directory': 'fabrics', 'file': SimpleUploadedFile('fabrics.csv', csv_data.encode('utf-8'))},
            format='multipart'), 201)
        self.assertEqual(len(up['mapping']), 5)
        job = up['job']['id']
        prev = self.ok(self.client.post(f'/api/md/import/{job}/preview/', {'mapping': up['mapping'], 'mode': 'create'},
                                        format='json'))
        self.assertEqual(prev['counts'], {'create': 2, 'update': 0, 'skip': 0, 'error': 0})
        self.assertEqual(self.client.get('/api/md/d/fabrics/').data['total'], 1)  # предпросмотр ничего не записал
        done = self.ok(self.client.post(f'/api/md/import/{job}/run/', {}, format='json'))
        self.assertEqual(done['status'], 'done')
        res = self.client.get('/api/md/d/fabrics/', {'kind': 'Кружево'}).data
        self.assertEqual(res['total'], 1)
        self.assertEqual(res['data'][0]['price_m'], 9800.5)

    # 10. Импорт каталога 100+ строк с ошибками в 3 строках
    def test_10_catalog_import_with_errors(self):
        import openpyxl
        self.supplier()

        def build(bad):
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.append(['Модель: артикул', 'Модель: наименование', 'Модель: категория', 'Модель: мероприятия',
                       'Модель: виды (стили)', 'Модель: цена аренды, ₸', 'Модель: цена продажи, ₸', 'Размер',
                       'Салон', 'Поставщик', 'Выдано в аренду, раз', 'Стоимость поступления, ₸'])
            for i in range(1, 106):
                art = f'СВ-{100 + (i + 1) // 2}'  # по 2 экземпляра на модель
                size = '42' if i % 2 else '44'
                cat = 'Свадебные платья'
                if bad and i == 10:
                    size = '99'          # нет такого размера
                if bad and i == 51:
                    cat = 'Ұзату'        # не конечная категория
                ws.append([art, f'Платье {art}', cat, 'Свадьба; Выпускной', 'королевское', 150000, 900000, size,
                           'Бутик 1', 'ТОО Поставщик', i % 7, 350000 if not (bad and i == 77) else 'дорого'])
            buf = io.BytesIO()
            wb.save(buf)
            return buf.getvalue()

        def upload(content):
            up = self.ok(self.client.post('/api/md/import/upload/', {
                'directory': 'items', 'file': SimpleUploadedFile('catalog.xlsx', content)}, format='multipart'), 201)
            self.assertEqual(len(up['mapping']), 12, up['mapping'])
            return up

        up = upload(build(True))
        job = up['job']['id']
        prev = self.ok(self.client.post(f'/api/md/import/{job}/preview/', {'mapping': up['mapping'],
                                                                           'mode': 'create'}, format='json'))
        self.assertEqual(prev['counts']['error'], 3, prev['errors'][:6])
        self.assertEqual(sorted({e['row'] for e in prev['errors']}), [11, 52, 78])
        self.assertTrue(all(e['column'] for e in prev['errors']))
        self.assertTrue(prev['has_error_file'])
        run = self.ok(self.client.post(f'/api/md/import/{job}/run/', {}, format='json'))
        self.assertEqual(run['status'], 'failed')          # целиком или никак (МД-31)
        self.assertEqual(m.Item.objects.filter(organization=self.org).count(), 0)
        self.assertEqual(self.client.get(f'/api/md/import/{job}/errors-file/').status_code, 200)
        # исправленный файл проходит целиком
        up = upload(build(False))
        job = up['job']['id']
        self.ok(self.client.post(f'/api/md/import/{job}/preview/', {'mapping': up['mapping'], 'mode': 'create',
                                                                    'profile_name': 'Каталог'}, format='json'))
        run = self.ok(self.client.post(f'/api/md/import/{job}/run/', {}, format='json'))
        self.assertEqual(run['status'], 'done', run)
        self.assertEqual(m.Item.objects.filter(organization=self.org).count(), 105)
        self.assertEqual(m.ProductModel.objects.filter(organization=self.org).count(), 53)
        it = m.Item.objects.filter(organization=self.org, model__article='СВ-101', size__value='42').first()
        self.assertEqual(it.article, 'СВ-101-42')
        self.assertEqual(it.rent_count, 1)
        self.assertTrue(m.ImportProfile.objects.filter(organization=self.org, name='Каталог').exists())
        # новый артикул продолжит нумерацию после импортированных
        self.assertEqual(self.create_dress()['article'], 'СВ-154')
        # журнал загрузок
        jobs = self.ok(self.client.get('/api/md/import/jobs/'))
        self.assertEqual(jobs[0]['status'], 'done')
        # режим обновления без колонки-ключа не запускается
        up = upload(build(True))
        r = self.client.post(f'/api/md/import/{up["job"]["id"]}/preview/', {'mapping': up['mapping'],
                                                                            'mode': 'upsert', 'key_field': 'tag'},
                             format='json')
        self.assertEqual(r.status_code, 400)

    # 11. ZIP с фото раскладывается по моделям по именам файлов
    def test_11_zip_photos(self):
        a = self.create_dress(article='СВ-117')
        b = self.create_dress(article='СВ-128')
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as z:
            z.writestr('СВ-117_1.jpg', jpeg_bytes())
            z.writestr('СВ-117_2.jpg', jpeg_bytes((200, 0, 0)))
            z.writestr('photos/СВ-128_1.jpg', jpeg_bytes())
            z.writestr('СВ-999_1.jpg', jpeg_bytes())
            z.writestr('readme.txt', 'x')
        rep = self.ok(self.client.post('/api/md/import/photos-zip/', {
            'file': SimpleUploadedFile('photos.zip', buf.getvalue())}, format='multipart'))
        self.assertEqual(rep['added'], 3)
        self.assertEqual(rep['models'], {'СВ-117': 2, 'СВ-128': 1})
        self.assertEqual(len(rep['skipped']), 2)
        ph = self.ok(self.client.get(f'/api/md/d/models/{a["id"]}/photos/'))
        self.assertEqual(len(ph), 2)
        self.assertTrue(ph[0]['is_main'])
        # превью и подписанная ссылка
        p = m.Photo.objects.filter(product_model_id=a['id']).first()
        self.assertTrue(p.thumb_300 and p.thumb_1200)
        url = ph[0]['thumb_300']
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.get(url.replace('sig=', 'sig=x')).status_code, 403)
        # фильтр «есть фото»
        self.assertEqual(self.client.get('/api/md/d/models/', {'has_photo': 'true'}).data['total'], 2)
        self.create_dress(name='Без фото')
        self.assertEqual(self.client.get('/api/md/d/models/', {'has_photo': 'false'}).data['total'], 1)
        del b

    # 12. Каждое изменение видно в «Истории» с автором и старым значением
    def test_12_history(self):
        model = self.create_dress()
        admin = self.api(self.make_user('admin@test.kz', 'admin'))
        self.ok(admin.patch(f'/api/md/d/models/{model["id"]}/', {'rent_price': 140000, 'name': 'Айгерим-2',
                                                                 'styles': [self.style('Воздушное')]}, format='json'))
        hist = self.ok(self.client.get(f'/api/md/d/models/{model["id"]}/history/'))
        self.assertEqual([h['action'] for h in hist], ['update', 'create'])
        self.assertEqual(hist[0]['user'], 'Admin')
        ch = {c['field']: c for c in hist[0]['changes']}
        self.assertEqual(ch['rent_price']['old'], '150000')
        self.assertEqual(ch['rent_price']['new'], '140000')
        self.assertEqual(ch['name']['old'], 'Платье «Айгерим»')
        self.assertEqual(ch['styles']['new'], 'Воздушное')
        # продавец видит историю только своих записей
        seller_u = self.make_user('s@test.kz', 'seller')
        seller = self.api(seller_u)
        self.assertEqual(seller.get(f'/api/md/d/models/{model["id"]}/history/').status_code, 403)
        own = self.create_dress(client=self.client, name='чужая')
        mine = self.ok(seller.post('/api/md/d/clients/', {'full_name': 'Клиент', 'phone': '+77070000001'},
                                   format='json'), 201)
        self.ok(seller.get(f'/api/md/d/clients/{mine["id"]}/history/'))
        del own

    # 13. Пользователь другой организации не видит ни одной записи
    def test_13_tenant_isolation(self):
        model = self.create_dress(article='СВ-117')
        item = self.create_item(model['id'], '44')
        client_rec = self.ok(self.client.post('/api/md/d/clients/', {'full_name': 'Анна', 'phone': '+77011234567'},
                                              format='json'), 201)
        other_org = Organization.objects.create(name='Чужой салон')
        stranger = self.api(self.make_user('x@other.kz', 'owner', org=other_org))
        for code in ('models', 'items', 'clients', 'kits'):
            self.assertEqual(stranger.get(f'/api/md/d/{code}/').data['total'], 0)
        for code, oid in (('models', model['id']), ('items', item['id']), ('clients', client_rec['id'])):
            self.assertEqual(stranger.get(f'/api/md/d/{code}/{oid}/').status_code, 404)
            self.assertEqual(stranger.patch(f'/api/md/d/{code}/{oid}/', {'note': 'x'}, format='json').status_code, 404)
        self.assertEqual(self.ok(stranger.get('/api/md/search/', {'q': 'СВ-117'}))['results'], [])
        # чужие id в ссылках — «не найдено»
        r = stranger.post('/api/md/d/models/', {'name': 'x', 'category': self.cat('Свадебные платья'),
                                                'events': [self.event('Свадьба')]}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('category', r.data['fields'])
        # чужая организация в заголовке — отказ
        r = stranger.get('/api/md/d/models/', HTTP_X_ORGANIZATION=str(self.org.pk))
        self.assertEqual(r.status_code, 403)
        # фото чужой организации недоступно по API
        self.assertEqual(stranger.get(f'/api/md/d/models/{model["id"]}/photos/').status_code, 404)
        # без токена — 401
        from rest_framework.test import APIClient
        self.assertEqual(APIClient().get('/api/md/d/models/').status_code, 401)
