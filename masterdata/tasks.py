"""Фоновые задачи (МД-35): долгий импорт — в фоне с индикатором прогресса.

Если настроен Celery (CELERY_BROKER_URL), задачи уходят в очередь Redis.
Иначе — выполняются в фоновом потоке процесса (подходит для одного сервера
и небольших объёмов). MD_TASKS_SYNC=True — выполнять сразу (тесты).
"""
import logging
import threading

from django.conf import settings
from django.db import close_old_connections, connection

log = logging.getLogger('masterdata')


def _run(job_id, apply):
    from . import importer
    from .models import ImportJob
    job = ImportJob.objects.get(pk=job_id)

    def progress(done, total):
        ImportJob.objects.filter(pk=job_id).update(processed_rows=done, total_rows=total)

    try:
        importer.process(job, apply=apply, progress=progress)
    except Exception as e:  # pragma: no cover - аварийный путь
        log.exception('[import] job %s failed', job_id)
        ImportJob.objects.filter(pk=job_id).update(status='failed', message=f'Внутренняя ошибка: {e}')


try:  # Celery — необязательная зависимость
    from celery import shared_task  # type: ignore

    @shared_task(name='masterdata.run_import_job')
    def run_import_job(job_id, apply):
        _run(job_id, apply)
    CELERY_OK = True
except Exception:  # pragma: no cover
    CELERY_OK = False


def _thread_target(job_id, apply):
    close_old_connections()
    try:
        _run(job_id, apply)
    finally:
        connection.close()


def start_job(job, apply, background):
    if settings.MD_TASKS_SYNC or not background:
        _run(job.pk, apply)
        return 'sync'
    if CELERY_OK and settings.CELERY_BROKER_URL:
        run_import_job.delay(str(job.pk), apply)
        return 'celery'
    threading.Thread(target=_thread_target, args=(job.pk, apply), daemon=True).start()
    return 'thread'
