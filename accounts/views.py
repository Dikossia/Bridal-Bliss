"""
Портировано из auth-module/server.js (Express) на Django.
Каждый API-эндпоинт сохраняет контракт (метод, путь, тело запроса/ответа) и
бизнес-логику оригинала, чтобы фронтенд (accounts/templates + assets/) можно
было использовать без изменений.
"""
import json
import logging
import mimetypes
import os
from datetime import timedelta

import jwt
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from . import utils
from .models import PasswordSetupToken, RefreshToken

logger = logging.getLogger('accounts')
User = get_user_model()

ASSETS_DIR = os.path.join(settings.BASE_DIR, 'assets')


def _json_body(request):
    try:
        return json.loads(request.body or b'{}')
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}


def _err(message, status=400):
    return JsonResponse({'ok': False, 'error': message}, status=status)


def _ok(extra=None, status=200):
    payload = {'ok': True}
    if extra:
        payload.update(extra)
    return JsonResponse(payload, status=status)


# ============================================================
# Страницы (аналог express.static + app.get('/register') и т.д.)
# ============================================================
def index_redirect(request):
    return redirect('/register')


def register_page(request):
    return render(request, 'accounts/register.html')


def login_page(request):
    return render(request, 'accounts/login.html')


def home_page(request):
    return render(request, 'accounts/home.html')


def dictionaries_page(request):
    return render(request, 'accounts/dictionaries.html')


def income_expense_page(request):
    return render(request, 'accounts/income-expense.html')


def set_password_page(request):
    return render(request, 'accounts/set-password.html')


def forgot_password_page(request):
    return render(request, 'accounts/forgot-password.html')


def reset_password_page(request):
    return render(request, 'accounts/reset-password.html')


def dashboard_stub(request):
    # Пример защищённого роута для проверки — как в оригинале (заглушка).
    return HttpResponse('Добро пожаловать в личный кабинет «Учёт»!')


# Явная карта — на минимальных Docker-образах (python:3.13-slim) системной
# /etc/mime.types может не быть, а mimetypes.guess_type() тогда возвращает
# None. Для .js это критично: браузер откажется выполнять ES-модуль
# (<script type="module">) без правильного text/javascript.
_EXT_CONTENT_TYPES = {
    '.js': 'text/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.html': 'text/html; charset=utf-8',
    '.svg': 'image/svg+xml',
    '.ico': 'image/x-icon',
    '.png': 'image/png',
    '.json': 'application/json',
}


def _serve_asset_file(root, relative_path):
    """Простая раздача статики без Django staticfiles/collectstatic —
    чтобы не трогать абсолютные пути вроде /styles.css, /shared/theme.js
    в уже готовом фронтенде. Для настоящего продакшн-трафика эти файлы
    также можно отдавать напрямую из Nginx (volume), см. README."""
    safe_rel = os.path.normpath(relative_path).lstrip(os.sep)
    if safe_rel.startswith('..'):
        raise Http404
    full_path = os.path.join(root, safe_rel)
    if not os.path.isfile(full_path):
        raise Http404
    ext = os.path.splitext(full_path)[1].lower()
    content_type = _EXT_CONTENT_TYPES.get(ext) or mimetypes.guess_type(full_path)[0] or 'application/octet-stream'
    with open(full_path, 'rb') as f:
        return HttpResponse(f.read(), content_type=content_type)


def serve_styles_css(request):
    return _serve_asset_file(ASSETS_DIR, 'styles.css')


def serve_shared_asset(request, path):
    return _serve_asset_file(os.path.join(ASSETS_DIR, 'shared'), path)


# ============================================================
# API: Регистрация
# ============================================================
@csrf_exempt
@require_POST
def api_register(request):
    ip = utils.client_ip(request)
    if not utils.check_rate_limit(f'register:{ip}', *settings.REGISTER_RATE_LIMIT):
        return _err('Слишком много запросов. Попробуйте позже.', 429)

    body = _json_body(request)
    email = str(body.get('email') or '').strip().lower()
    name = str(body.get('name') or '').strip()
    phone = str(body.get('phone') or '').strip()

    if not utils.is_valid_email(email):
        return _err('Некорректный email')
    if not (2 <= len(name) <= 100):
        return _err('Имя должно содержать от 2 до 100 символов')
    if not utils.is_valid_phone(phone):
        return _err('Некорректный телефон')

    duplicate_active = False
    raw_token = None
    try:
        with transaction.atomic():
            user = User.objects.select_for_update().filter(email=email).first()

            if user is None:
                user = User.objects.create_user(email=email, name=name, phone=phone)
            elif user.status == User.STATUS_ACTIVE:
                duplicate_active = True
            else:
                user.name = name
                user.phone = phone
                user.save(update_fields=['name', 'phone'])
                PasswordSetupToken.objects.filter(user=user, used_at__isnull=True).delete()

            if not duplicate_active:
                raw_token = utils.new_raw_token()
                PasswordSetupToken.objects.create(
                    user=user,
                    token_hash=utils.sha256hex(raw_token),
                    expires_at=timezone.now() + timedelta(hours=settings.TOKEN_TTL_HOURS),
                )
    except Exception:
        logger.exception('[register] error')
        return _err('Внутренняя ошибка сервера', 500)

    if duplicate_active:
        # Anti-enumeration: снаружи выглядит как успех, но владельцу уходит уведомление.
        try:
            utils.send_duplicate_registration_email(email, user.name)
        except Exception:
            logger.exception('[register] duplicate-notification mail failed')
        return _ok()

    try:
        utils.send_setup_email(email, name, raw_token)
    except Exception:
        logger.exception('[register] mail send failed')

    return _ok()


# ============================================================
# API: Проверка токена (регистрация / сброс)
# ============================================================
@require_GET
def api_verify_token(request):
    raw = request.GET.get('token', '')
    if not utils.is_hex64(raw):
        return JsonResponse({'ok': False})
    token_hash = utils.sha256hex(raw)
    exists = PasswordSetupToken.objects.filter(
        token_hash=token_hash, used_at__isnull=True, expires_at__gt=timezone.now()
    ).exists()
    return JsonResponse({'ok': exists})


# ============================================================
# API: Установка пароля (после регистрации)
# ============================================================
@csrf_exempt
@require_POST
def api_set_password(request):
    body = _json_body(request)
    raw = str(body.get('token') or '')
    password = str(body.get('password') or '')

    if not utils.is_hex64(raw):
        return _err('Некорректный токен')
    if not utils.is_strong_password(password):
        return _err('Пароль не соответствует требованиям')

    token_hash = utils.sha256hex(raw)
    try:
        with transaction.atomic():
            tok = (PasswordSetupToken.objects
                   .select_for_update()
                   .filter(token_hash=token_hash, used_at__isnull=True, expires_at__gt=timezone.now())
                   .first())
            if tok is None:
                return _err('Ссылка недействительна или истекла')

            user = User.objects.select_for_update().get(pk=tok.user_id)
            user.set_password(password)
            user.status = User.STATUS_ACTIVE
            user.activated_at = timezone.now()
            user.save(update_fields=['password', 'status', 'activated_at', 'is_active'])

            tok.used_at = timezone.now()
            tok.save(update_fields=['used_at'])
            PasswordSetupToken.objects.filter(user=user, used_at__isnull=True).delete()
    except Exception:
        logger.exception('[set-password] error')
        return _err('Внутренняя ошибка сервера', 500)

    return _ok()


# ============================================================
# API: Запрос сброса пароля
# ============================================================
@csrf_exempt
@require_POST
def api_forgot_password(request):
    ip = utils.client_ip(request)
    if not utils.check_rate_limit(f'forgot-password:{ip}', *settings.REGISTER_RATE_LIMIT):
        return _err('Слишком много запросов. Попробуйте позже.', 429)

    body = _json_body(request)
    email = str(body.get('email') or '').strip().lower()
    if not utils.is_valid_email(email):
        return _err('Некорректный email')

    user = User.objects.filter(email=email).first()
    # Anti-enumeration: если пользователя нет или он не активен — имитируем успех.
    if user is None or user.status != User.STATUS_ACTIVE:
        return _ok()

    raw_token = None
    try:
        with transaction.atomic():
            PasswordSetupToken.objects.filter(user=user, used_at__isnull=True).delete()
            raw_token = utils.new_raw_token()
            PasswordSetupToken.objects.create(
                user=user,
                token_hash=utils.sha256hex(raw_token),
                expires_at=timezone.now() + timedelta(hours=settings.RESET_TOKEN_TTL_HOURS),
            )
    except Exception:
        logger.exception('[forgot-password] error')
        return _err('Внутренняя ошибка сервера', 500)

    try:
        utils.send_reset_email(email, user.name, raw_token)
    except Exception:
        logger.exception('[forgot-password] mail send failed')

    return _ok()


# ============================================================
# API: Сброс пароля по токену
# ============================================================
@csrf_exempt
@require_POST
def api_reset_password(request):
    body = _json_body(request)
    raw = str(body.get('token') or '')
    password = str(body.get('password') or '')

    if not utils.is_hex64(raw):
        return _err('Некорректный токен')
    if not utils.is_strong_password(password):
        return _err('Пароль не соответствует требованиям')

    token_hash = utils.sha256hex(raw)
    try:
        with transaction.atomic():
            tok = (PasswordSetupToken.objects
                   .select_for_update()
                   .filter(token_hash=token_hash, used_at__isnull=True, expires_at__gt=timezone.now())
                   .first())
            if tok is None:
                return _err('Ссылка недействительна или истекла')

            user = User.objects.select_for_update().get(pk=tok.user_id)

            if user.has_usable_password() and user.check_password(password):
                return _err('Новый пароль не должен совпадать со старым паролем')

            user.set_password(password)
            user.save(update_fields=['password'])

            tok.used_at = timezone.now()
            tok.save(update_fields=['used_at'])

            # Безопасность: уничтожаем все активные сессии пользователя.
            RefreshToken.objects.filter(user=user).delete()
    except Exception:
        logger.exception('[reset-password] error')
        return _err('Внутренняя ошибка сервера', 500)

    return _ok()


# ============================================================
# API: Вход
# ============================================================
@csrf_exempt
@require_POST
def api_login(request):
    ip = utils.client_ip(request)
    if not utils.check_rate_limit(f'login:{ip}', *settings.LOGIN_RATE_LIMIT):
        return _err('Слишком много попыток входа. Попробуйте позже.', 429)

    body = _json_body(request)
    email = str(body.get('email') or '').strip().lower()
    password = str(body.get('password') or '')

    if not email or not password:
        return _err('Email и пароль обязательны')

    user = User.objects.filter(email=email).first()
    if user is None:
        return _err('Неверный email или пароль', 401)

    if user.status != User.STATUS_ACTIVE:
        return _err('Учетная запись не активирована или заблокирована', 403)

    if not user.has_usable_password() or not user.check_password(password):
        return _err('Неверный email или пароль', 401)

    access_token = utils.issue_access_token(user)

    session_started_at = timezone.now()
    expires_at = utils.compute_refresh_expiry(session_started_at)
    raw_refresh = utils.new_raw_token()

    RefreshToken.objects.create(
        user=user,
        token_hash=utils.sha256hex(raw_refresh),
        expires_at=expires_at,
        session_started_at=session_started_at,
    )
    user.last_login = timezone.now()
    user.save(update_fields=['last_login'])

    resp = JsonResponse({
        'ok': True,
        'accessToken': access_token,
        'user': {'name': user.name, 'email': user.email},
    })
    utils.set_refresh_cookie(resp, raw_refresh, expires_at)
    return resp


# ============================================================
# API: Обновление пары токенов
# ============================================================
@csrf_exempt
@require_POST
def api_refresh(request):
    raw_refresh = request.COOKIES.get('refreshToken')
    if not raw_refresh:
        return _err('Токен возобновления отсутствует', 401)

    token_hash = utils.sha256hex(raw_refresh)
    try:
        with transaction.atomic():
            tok = (RefreshToken.objects
                   .select_for_update()
                   .filter(token_hash=token_hash, expires_at__gt=timezone.now())
                   .first())
            if tok is None:
                return _err('Токен недействителен или истёк', 401)

            user = User.objects.filter(pk=tok.user_id).first()
            if user is None or user.status != User.STATUS_ACTIVE:
                return _err('Пользователь недоступен', 403)

            new_access_token = utils.issue_access_token(user)

            session_started_at = tok.session_started_at
            tok.delete()

            new_raw_refresh = utils.new_raw_token()
            new_expires_at = utils.compute_refresh_expiry(session_started_at)
            RefreshToken.objects.create(
                user=user,
                token_hash=utils.sha256hex(new_raw_refresh),
                expires_at=new_expires_at,
                session_started_at=session_started_at,
            )
    except Exception:
        logger.exception('[refresh] error')
        return _err('Внутренняя ошибка сервера', 500)

    resp = JsonResponse({'ok': True, 'accessToken': new_access_token})
    utils.set_refresh_cookie(resp, new_raw_refresh, new_expires_at)
    return resp


# ============================================================
# API: Выход
# ============================================================
@csrf_exempt
@require_POST
def api_logout(request):
    raw_refresh = request.COOKIES.get('refreshToken')
    if raw_refresh:
        RefreshToken.objects.filter(token_hash=utils.sha256hex(raw_refresh)).delete()
    resp = JsonResponse({'ok': True})
    utils.clear_refresh_cookie(resp)
    return resp


# ============================================================
# Middleware-аналог authenticateToken из оригинала — доступен для будущих
# защищённых API (в оригинале тоже был объявлен, но нигде не подключён).
# ============================================================
def authenticate_token(view_func):
    def wrapped(request, *args, **kwargs):
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        token = auth_header.split(' ')[1] if auth_header.startswith('Bearer ') else None
        if not token:
            return _err('Токен отсутствует', 401)
        try:
            request.jwt_user = utils.decode_access_token(token)
        except jwt.PyJWTError:
            return _err('Токен недействителен или истёк', 403)
        return view_func(request, *args, **kwargs)
    return wrapped
