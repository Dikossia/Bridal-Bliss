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
