"""Шифрование персональных данных (ИИН, номер документа) — ТЗ §8.

Ключ берётся из MD_FIELD_ENCRYPTION_KEY (Fernet, urlsafe-base64 32 байта).
Если не задан — выводится из SECRET_KEY (удобно для разработки; в проде
задайте отдельный ключ и храните его вне БД/бэкапов БД).
Для поиска и проверки уникальности хранится HMAC-хеш значения.
"""
import base64
import hashlib
import hmac

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import models


def _key() -> bytes:
    k = getattr(settings, 'MD_FIELD_ENCRYPTION_KEY', '') or ''
    if k:
        return k.encode()
    digest = hashlib.sha256(('md-fernet:' + settings.SECRET_KEY).encode()).digest()
    return base64.urlsafe_b64encode(digest)


def _fernet():
    return Fernet(_key())


def encrypt(value: str) -> str:
    if value in (None, ''):
        return ''
    return _fernet().encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    if not token:
        return ''
    try:
        return _fernet().decrypt(token.encode()).decode()
    except (InvalidToken, ValueError):
        return ''


def blind_hash(value: str) -> str:
    """Детерминированный HMAC для уникальности/поиска по точному значению."""
    if not value:
        return ''
    return hmac.new(_key(), value.encode(), hashlib.sha256).hexdigest()


class EncryptedCharField(models.TextField):
    """Хранит значение зашифрованным; в Python-коде — открытый текст."""

    def from_db_value(self, value, expression, connection):
        return decrypt(value) if value else (value or '')

    def to_python(self, value):
        return value or ''

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        return encrypt(value) if value else ''
