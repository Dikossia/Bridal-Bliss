from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.utils import timezone

from .managers import UserManager


class User(AbstractBaseUser, PermissionsMixin):
    """
    Таблица `users` из schema.sql. password_hash из оригинала — это
    встроенное поле `password` (AbstractBaseUser), пустое/unusable, пока
    пользователь не задал пароль (аналог password_hash IS NULL).
    """
    STATUS_PENDING = 'pending'
    STATUS_ACTIVE = 'active'
    STATUS_DISABLED = 'disabled'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'pending'),
        (STATUS_ACTIVE, 'active'),
        (STATUS_DISABLED, 'disabled'),
    ]

    email = models.EmailField(unique=True)
    name = models.CharField(max_length=100)
    phone = models.CharField(max_length=20)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)

    created_at = models.DateTimeField(auto_now_add=True)
    activated_at = models.DateTimeField(null=True, blank=True)
    # last_login уже есть в AbstractBaseUser — используем его как last_login_at.

    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=False)  # синхронизируется со `status` в save()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['name', 'phone']

    objects = UserManager()

    class Meta:
        db_table = 'users'

    def __str__(self):
        return self.email

    def save(self, *args, **kwargs):
        if self.email:
            self.email = self.email.strip().lower()
        self.is_active = (self.status == self.STATUS_ACTIVE)
        super().save(*args, **kwargs)


class PasswordSetupToken(models.Model):
    """
    Таблица `password_setup_tokens`. Одна таблица на два сценария —
    установка пароля при регистрации (TTL=TOKEN_TTL_HOURS) и сброс пароля
    (TTL=RESET_TOKEN_TTL_HOURS) — так же, как в оригинальном auth-модуле.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='setup_tokens')
    token_hash = models.CharField(max_length=64, unique=True)  # SHA-256 hex
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'password_setup_tokens'
        indexes = [
            models.Index(fields=['user']),
            models.Index(fields=['expires_at']),
        ]

    def is_valid(self):
        return self.used_at is None and self.expires_at > timezone.now()


class RefreshToken(models.Model):
    """
    Таблица `refresh_tokens`. Хранится только SHA-256 хеш; сырой токен —
    только в httpOnly-куке клиента. expires_at — ближайший из дедлайнов:
    idle (сдвигается при /api/refresh) и абсолютный (от session_started_at).
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='refresh_tokens')
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    session_started_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'refresh_tokens'
        indexes = [
            models.Index(fields=['user']),
            models.Index(fields=['expires_at']),
        ]


class RateLimitHit(models.Model):
    """
    Простой rate-limit на БД (аналог express-rate-limit из оригинала, но
    корректно работающий сразу для нескольких воркеров gunicorn — в отличие
    от in-memory-счётчика одного Node-процесса). См. accounts/utils.py.
    """
    key = models.CharField(max_length=200, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'rate_limit_hits'


# ============================================================
# Организации и роли (нужны модулю «Мастер-данные», ТЗ §1 и §6).
# Каждая запись мастер-данных принадлежит организации (салону/сети
# салонов). Пользователь состоит в организации с одной из ролей.
# ============================================================
import uuid  # noqa: E402


class Organization(models.Model):
    """Организация (салон или сеть бутиков). Данные разных организаций
    полностью изолированы по organization_id (ТЗ §6)."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField('Название', max_length=200)
    # Настройки организации: включённые разделы (МД-6) и т.п.
    # {"sections": {"uzatu": true, "shoes": false}}
    settings = models.JSONField('Настройки', default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'organizations'
        verbose_name = 'Организация'
        verbose_name_plural = 'Организации'

    def __str__(self):
        return self.name

    # ---- Разделы (МД-6) ----
    DEFAULT_SECTIONS = {'uzatu': True, 'shoes': False}

    def sections(self):
        s = dict(self.DEFAULT_SECTIONS)
        s.update((self.settings or {}).get('sections') or {})
        return s

    def section_enabled(self, key):
        if not key:
            return True
        return bool(self.sections().get(key, True))


class Membership(models.Model):
    """Пользователь в организации с ролью (ТЗ §6)."""
    ROLE_OWNER = 'owner'
    ROLE_ADMIN = 'admin'
    ROLE_SELLER = 'seller'
    ROLE_ACCOUNTANT = 'accountant'
    ROLE_CHOICES = [
        (ROLE_OWNER, 'Владелец'),
        (ROLE_ADMIN, 'Администратор'),
        (ROLE_SELLER, 'Продавец'),
        (ROLE_ACCOUNTANT, 'Бухгалтер'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='memberships')
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='memberships')
    role = models.CharField('Роль', max_length=20, choices=ROLE_CHOICES, default=ROLE_SELLER)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'organization_memberships'
        unique_together = [('user', 'organization')]
        verbose_name = 'Участник организации'
        verbose_name_plural = 'Участники организаций'

    def __str__(self):
        return f'{self.user} — {self.organization} ({self.get_role_display()})'
