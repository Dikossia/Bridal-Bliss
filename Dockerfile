FROM python:3.13-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=config.settings

# Системные зависимости для psycopg (сборка при отсутствии бинарных колёс)
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# collectstatic нужен только для статики Django-админки (django.contrib.admin);
# фронтенд «Учёт» (public/shared) отдаётся отдельными вьюхами, см. accounts/views.py.
# SECRET_KEY не важен на этом шаге — БД не требуется (USE_SQLITE_FOR_BUILD не нужен,
# collectstatic вообще не обращается к БД).
RUN python manage.py collectstatic --noinput

RUN addgroup --system app && adduser --system --ingroup app app \
    && chown -R app:app /app
USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/register', timeout=2).status==200 else 1)" || exit 1

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
