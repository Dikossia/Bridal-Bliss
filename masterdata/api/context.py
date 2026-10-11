"""Организация и права текущего запроса (§6).

Организация определяется по заголовку X-Organization (UUID) либо берётся
первая активная организация пользователя. Пользователь без членства в
организации не видит ни одной записи (изоляция по organization_id).
"""
from functools import cached_property

from rest_framework import exceptions

from accounts.models import Membership

from ..models import RolePolicy
from ..seed import default_policy

ACTIONS = ('view', 'create', 'update', 'archive', 'import', 'export')


class Policy:
    def __init__(self, role, code, row=None):
        self.role, self.code = role, code
        if row is not None:
            self.can = {'view': row.can_view, 'create': row.can_create, 'update': row.can_update,
                        'archive': row.can_archive, 'import': row.can_import, 'export': row.can_export}
            self.history = row.history
            self.hidden = set(row.hidden_fields or [])
            self.readonly = set(row.readonly_fields or [])
        else:
            p = default_policy(role, code)
            self.can = {'view': p['view'], 'create': p['create'], 'update': p['update'],
                        'archive': p['archive'], 'import': p['imp'], 'export': p['export']}
            self.history = p['history']
            self.hidden = set(p.get('hidden', []))
            self.readonly = set(p.get('readonly', []))
        if not self.can['view']:
            for k in self.can:
                self.can[k] = False

    def as_dict(self):
        return {**{k: v for k, v in self.can.items()}, 'history': self.history,
                'hidden_fields': sorted(self.hidden), 'readonly_fields': sorted(self.readonly)}


class MDContext:
    def __init__(self, request):
        self.request = request
        self.user = request.user
        self._policies = {}

    @cached_property
    def membership(self):
        qs = Membership.objects.select_related('organization').filter(user=self.user, is_active=True)
        org_id = self.request.META.get('HTTP_X_ORGANIZATION') or self.request.GET.get('org')
        if org_id:
            try:
                m = qs.filter(organization_id=org_id).first()
            except Exception:
                m = None
            if m is None:
                raise exceptions.PermissionDenied('Нет доступа к организации')
            return m
        m = qs.order_by('created_at').first()
        if m is None:
            raise exceptions.PermissionDenied('Пользователь не состоит ни в одной организации')
        return m

    @property
    def org(self):
        return self.membership.organization

    @property
    def role(self):
        return self.membership.role

    @property
    def is_manager(self):
        """Владелец/администратор: структура, настройки организации (§6)."""
        return self.role in ('owner', 'admin')

    def policy(self, code) -> Policy:
        if code not in self._policies:
            row = RolePolicy.objects.filter(organization=self.org, role=self.role, directory_code=code).first()
            self._policies[code] = Policy(self.role, code, row)
        return self._policies[code]

    def require(self, code, action):
        if not self.policy(code).can.get(action):
            names = {'view': 'просмотр', 'create': 'создание', 'update': 'изменение', 'archive': 'архивирование',
                     'import': 'импорт', 'export': 'экспорт'}
            raise exceptions.PermissionDenied(f'Нет прав на {names.get(action, action)}')

    def require_manager(self):
        if not self.is_manager:
            raise exceptions.PermissionDenied('Действие доступно владельцу и администратору')


def md(request) -> MDContext:
    ctx = getattr(request, '_md_ctx', None)
    if ctx is None:
        ctx = MDContext(request)
        request._md_ctx = ctx
    return ctx
