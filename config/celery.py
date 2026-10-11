"""Celery для фоновых задач модуля «Мастер-данные» (импорт, МД-35).
Запуск воркера: celery -A config worker -l info"""
import os

from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
app = Celery('dress')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks(['masterdata'])
