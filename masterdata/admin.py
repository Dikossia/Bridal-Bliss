"""Админка Django — только для суперадминистратора системы (ТЗ §7).
Пользователи салона работают в собственном интерфейсе /md."""
from django.contrib import admin

from accounts.models import Membership, Organization

from . import models as m


class SuperuserOnly(admin.ModelAdmin):
    def has_module_permission(self, request):
        return request.user.is_active and request.user.is_superuser

    has_view_permission = has_add_permission = has_change_permission = has_delete_permission = \
        lambda self, request, obj=None: request.user.is_active and request.user.is_superuser


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 0
    autocomplete_fields = ['user']


@admin.register(Organization)
class OrganizationAdmin(SuperuserOnly):
    list_display = ['name', 'created_at']
    search_fields = ['name']
    inlines = [MembershipInline]


@admin.register(Membership)
class MembershipAdmin(SuperuserOnly):
    list_display = ['user', 'organization', 'role', 'is_active']
    list_filter = ['role', 'organization']
    search_fields = ['user__email', 'organization__name']


def org_admin(model, display, search=('name',), filters=()):
    attrs = {'list_display': list(display) + ['organization', 'is_active'], 'search_fields': list(search),
             'list_filter': ['organization', 'is_active', *filters], 'readonly_fields': ['created_at', 'updated_at']}
    admin.site.register(model, type(f'{model.__name__}Admin', (SuperuserOnly,), attrs))


org_admin(m.ProductModel, ['article', 'name', 'category', 'operations', 'rent_price'], ('article', 'name'))
org_admin(m.Item, ['tag', 'model', 'size', 'salon', 'stage', 'status'], ('tag', 'barcode', 'model__article'),
          ('status',))
org_admin(m.Kit, ['code', 'name'], ('code', 'name'))
org_admin(m.Category, ['name', 'parent', 'article_prefix', 'section', 'is_enabled'], ('name',))
org_admin(m.Client, ['full_name', 'phone', 'city'], ('full_name', 'phone_digits'))
org_admin(m.Counterparty, ['name', 'kind', 'bin_iin'], ('name', 'bin_iin'))
org_admin(m.Account, ['name', 'parent', 'pnl', 'cashflow', 'func_area'], ('name',))
for mdl in (m.Event, m.Style, m.Color, m.Manufacturer, m.PhotoType, m.DefectType, m.Stage, m.Salon,
            m.DepositOption):
    org_admin(mdl, ['name'])
org_admin(m.Size, ['system', 'value'], ('value',))
org_admin(m.Country, ['iso_code', 'name'], ('name', 'iso_code'))
org_admin(m.Directory, ['code', 'name', 'menu_group', 'is_system'], ('code', 'name'))
org_admin(m.DirectoryRecord, ['directory', 'code'], ('code',))


@admin.register(m.AuditLog)
class AuditLogAdmin(SuperuserOnly):
    list_display = ['at', 'organization', 'entity', 'record_repr', 'action', 'user', 'source']
    list_filter = ['organization', 'entity', 'action', 'source']
    search_fields = ['record_repr', 'record_id']


@admin.register(m.ImportJob)
class ImportJobAdmin(SuperuserOnly):
    list_display = ['created_at', 'organization', 'directory_code', 'original_name', 'status', 'user']
    list_filter = ['organization', 'status', 'directory_code']
