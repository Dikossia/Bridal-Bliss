import shutil
import tempfile

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from accounts.models import Membership, Organization, User
from accounts.utils import issue_access_token
from masterdata import models as m

TMP_MEDIA = tempfile.mkdtemp(prefix='md-test-media-')


@override_settings(MEDIA_ROOT=TMP_MEDIA, MD_TASKS_SYNC=True,
                   PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
                   STORAGES={'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
                             'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class MDTestCase(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TMP_MEDIA, ignore_errors=True)

    def setUp(self):
        self.org = Organization.objects.create(name='Салон «Невеста»')
        self.owner = self.make_user('owner@test.kz', 'owner')
        self.client = self.api(self.owner)

    def make_user(self, email, role, org=None):
        u = User.objects.create_user(email=email, name=email.split('@')[0].title(), phone='+77010000000')
        u.status = User.STATUS_ACTIVE
        u.save()
        Membership.objects.create(user=u, organization=org or self.org, role=role)
        return u

    def api(self, user):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION='Bearer ' + issue_access_token(user))
        return c

    # ---- helpers ----
    def ok(self, resp, code=200):
        self.assertEqual(resp.status_code, code, getattr(resp, 'data', resp.content))
        return resp.data.get('data') if hasattr(resp, 'data') and isinstance(resp.data, dict) else resp

    def get_id(self, model, **kw):
        return str(model.objects.get(organization=self.org, **kw).pk)

    def cat(self, name):
        return self.get_id(m.Category, name=name)

    def event(self, name):
        return self.get_id(m.Event, name=name)

    def style(self, name):
        return self.get_id(m.Style, name=name)

    def size(self, v):
        return self.get_id(m.Size, value=v, system='RU')

    def salon(self, i=0):
        return str(m.Salon.objects.filter(organization=self.org).order_by('name')[i].pk)

    def supplier(self):
        cp = m.Counterparty.objects.filter(organization=self.org, name='ТОО Поставщик').first()
        if cp is None:
            cp = m.Counterparty.objects.create(organization=self.org, name='ТОО Поставщик', kind='too',
                                               roles=['dress_supplier'])
        return str(cp.pk)

    def create_dress(self, client=None, **kw):
        data = {'name': 'Платье «Айгерим»', 'category': self.cat('Свадебные платья'),
                'events': [self.event('Свадьба')], 'operations': 'both', 'rent_price': 150000,
                'min_rent_price': 100000, 'sale_price': 900000}
        data.update(kw)
        return self.ok((client or self.client).post('/api/md/d/models/', data, format='json'), 201)

    def create_item(self, model_id, size=None, client=None, **kw):
        data = {'model': model_id, 'salon': self.salon(), 'supplier': self.supplier(), 'condition': 'new'}
        if size:
            data['size'] = self.size(size)
        data.update(kw)
        return self.ok((client or self.client).post('/api/md/d/items/', data, format='json'), 201)
