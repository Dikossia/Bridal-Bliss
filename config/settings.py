"""
Django settings for dress-rental (аренда свадебных платьев).

Имена переменных окружения намеренно совпадают с deploy-guide.md (шаг 5),
чтобы .env, собранный по гайду, подошёл без правок. Дополнительные
переменные (SMTP_*, JWT_SECRET, токены) — для портированного auth-модуля.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')


def env_bool(name, default=False):
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ('1', 'true', 'yes', 'on')


# ------------------- Базовое -------------------
SECRET_KEY = os.environ.get('SECRET_KEY', 'insecure-dev-key-change-me')
DEBUG = env_bool('DEBUG', False)

ALLOWED_HOSTS = [h.strip() for h in os.environ.get('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',') if h.strip()]
CSRF_TRUSTED_ORIGINS = [o.strip() for o in os.environ.get('CSRF_TRUSTED_ORIGINS', '').split(',') if o.strip()]

AUTH_USER_MODEL = 'accounts.User'

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'accounts',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'

# ------------------- База данных -------------------
# DB_* — те же имена, что в deploy-guide.md, шаг 5.
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('DB_NAME', 'dress_db'),
        'USER': os.environ.get('DB_USER', 'dress_app'),
        'PASSWORD': os.environ.get('DB_PASSWORD', ''),
        'HOST': os.environ.get('DB_HOST', 'postgres'),
        'PORT': os.environ.get('DB_PORT', '5432'),
        'CONN_MAX_AGE': 60,
    }
}

# Позволяет `python manage.py check` / `collectstatic` работать без Postgres
# (например, на этапе сборки Docker-образа) — реальное подключение
# используется только при первом запросе к БД.
if env_bool('USE_SQLITE_FOR_BUILD', False):
    DATABASES['default'] = {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'build.sqlite3',
    }

AUTH_PASSWORD_VALIDATORS = []  # своя проверка силы пароля — см. accounts/utils.py

LANGUAGE_CODE = 'ru-ru'
TIME_ZONE = 'Asia/Qyzylorda'
USE_I18N = True
USE_TZ = True

# ------------------- Статика -------------------
# ВАЖНО: /styles.css и /shared/* отдаются отдельными вьюхами (accounts/views.py),
# НЕ через STATIC_URL — чтобы не переписывать существующий фронтенд (там
# абсолютные пути вида /styles.css, /shared/theme.js). STATIC_URL здесь нужен
# только для стандартной статики Django (админка и т.п.).
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'},
}

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ------------------- Приложение «Учёт»/auth (портировано из auth-module) -------------------
APP_BASE_URL = os.environ.get('APP_BASE_URL', 'http://localhost:8000')
USE_SECURE_COOKIE = APP_BASE_URL.startswith('https://')

TOKEN_TTL_HOURS = int(os.environ.get('TOKEN_TTL_HOURS', '24'))
RESET_TOKEN_TTL_HOURS = int(os.environ.get('RESET_TOKEN_TTL_HOURS', '1'))

REFRESH_TTL_HOURS = int(os.environ.get('REFRESH_TTL_HOURS', '24'))       # абсолютный потолок сессии
IDLE_TIMEOUT_MINUTES = int(os.environ.get('IDLE_TIMEOUT_MINUTES', '60'))  # таймаут бездействия

JWT_SECRET = os.environ.get('JWT_SECRET') or SECRET_KEY
JWT_ALGORITHM = 'HS256'
JWT_ACCESS_TTL_MINUTES = int(os.environ.get('JWT_ACCESS_TTL_MINUTES', '15'))

# bcrypt (через встроенный хешер Django, cost по умолчанию bcrypt = 12,
# как и в оригинальном Node-модуле)
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.BCryptSHA256PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2PasswordHasher',
]

# Rate limiting (собственная реализация на БД — accounts/utils.py, см. README:
# работает корректно при нескольких воркерах gunicorn, в отличие от
# in-memory-лимитера в оригинальном Node-модуле).
REGISTER_RATE_LIMIT = (5, 15 * 60)   # 5 запросов / 15 минут — регистрация и forgot-password
LOGIN_RATE_LIMIT = (10, 15 * 60)     # 10 попыток / 15 минут — вход

# ------------------- SMTP -------------------
EMAIL_BACKEND = os.environ.get('EMAIL_BACKEND', 'django.core.mail.backends.smtp.EmailBackend')
EMAIL_HOST = os.environ.get('SMTP_HOST', '')
EMAIL_PORT = int(os.environ.get('SMTP_PORT', '587'))
EMAIL_HOST_USER = os.environ.get('SMTP_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('SMTP_PASSWORD', '')
EMAIL_USE_TLS = env_bool('SMTP_USE_TLS', not env_bool('SMTP_SECURE', False))
EMAIL_USE_SSL = env_bool('SMTP_SECURE', False)
DEFAULT_FROM_EMAIL = os.environ.get('SMTP_FROM', 'no-reply@platya.kz')

SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
USE_X_FORWARDED_HOST = True
