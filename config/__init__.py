# Celery подключается, только если пакет установлен (фоновый импорт, МД-35).
try:  # pragma: no cover
    from .celery import app as celery_app  # noqa: F401
except ImportError:  # pragma: no cover
    celery_app = None
