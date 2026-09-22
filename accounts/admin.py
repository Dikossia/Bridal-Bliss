from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import PasswordSetupToken, RefreshToken, User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    ordering = ['-created_at']
    list_display = ['email', 'name', 'phone', 'status', 'is_staff', 'created_at', 'last_login']
    list_filter = ['status', 'is_staff', 'is_superuser']
    search_fields = ['email', 'name', 'phone']
    readonly_fields = ['created_at', 'activated_at', 'last_login']

    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Профиль', {'fields': ('name', 'phone', 'status')}),
        ('Права', {'fields': ('is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Даты', {'fields': ('created_at', 'activated_at', 'last_login')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'name', 'phone', 'password1', 'password2', 'status', 'is_staff', 'is_superuser'),
        }),
    )


@admin.register(PasswordSetupToken)
class PasswordSetupTokenAdmin(admin.ModelAdmin):
    list_display = ['user', 'expires_at', 'used_at', 'created_at']
    list_filter = ['used_at']
    search_fields = ['user__email']
    readonly_fields = ['token_hash', 'created_at']


@admin.register(RefreshToken)
class RefreshTokenAdmin(admin.ModelAdmin):
    list_display = ['user', 'session_started_at', 'expires_at', 'created_at']
    search_fields = ['user__email']
    readonly_fields = ['token_hash', 'created_at']
