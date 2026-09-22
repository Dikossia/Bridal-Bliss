import hashlib
import re
import secrets
from datetime import timedelta

import jwt
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.utils import timezone
from django.utils.html import escape

from .models import RateLimitHit

EMAIL_RE = re.compile(r'^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$')
PHONE_RE = re.compile(r'^\+?[0-9\s\-()]{10,20}$')
HEX64_RE = re.compile(r'^[a-f0-9]{64}$')

SPECIAL_CHARS_RE = re.compile(r'[!@#$%^&*()_+\-=\[\]{};\':"\\|,.<>/?]')


def is_valid_email(value):
    return bool(EMAIL_RE.match(value or ''))


def is_valid_phone(value):
    return bool(PHONE_RE.match(value or ''))


def is_strong_password(pwd):
    """Как в оригинале: >=10 символов, буква, цифра, спецсимвол."""
    if not isinstance(pwd, str) or len(pwd) < 10:
        return False
    if not re.search(r'[A-Za-z]', pwd):
        return False
    if not re.search(r'[0-9]', pwd):
        return False
    if not SPECIAL_CHARS_RE.search(pwd):
        return False
    return True


def sha256hex(raw: str) -> str:
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def new_raw_token() -> str:
    """32 случайных байта в hex — 64 символа, как crypto.randomBytes(32) в оригинале."""
    return secrets.token_hex(32)


def is_hex64(value: str) -> bool:
    return bool(HEX64_RE.match(value or ''))


# ------------------- Email -------------------
def _send_html_mail(to_email, subject, html_body):
    msg = EmailMultiAlternatives(subject=subject, body=html_body, to=[to_email])
    msg.attach_alternative(html_body, 'text/html')
    msg.send(fail_silently=False)


def send_setup_email(to_email, name, raw_token):
    url = f'{settings.APP_BASE_URL}/set-password?token={raw_token}'
    html = f"""
    <div style="font-family:Arial,Helvetica,sans-serif;max-width:560px;margin:auto;color:#222">
      <h2 style="color:#2855af">Здравствуйте, {escape(name)}!</h2>
      <p>Спасибо за регистрацию в системе «Учёт». Чтобы завершить регистрацию, установите пароль:</p>
      <p style="text-align:center;margin:32px 0">
        <a href="{url}"
           style="background:#2855af;color:#fff;text-decoration:none;
                  padding:12px 24px;border-radius:6px;display:inline-block;font-weight:600">
          Установить пароль
        </a>
      </p>
      <p style="font-size:13px;color:#666">Если кнопка не работает, скопируйте ссылку в браузер:<br>
        <a href="{url}">{url}</a>
      </p>
      <p style="font-size:13px;color:#666">Ссылка действительна {settings.TOKEN_TTL_HOURS} часа. Если вы не регистрировались — просто проигнорируйте это письмо.</p>
    </div>"""
    _send_html_mail(to_email, 'Завершите регистрацию в системе Учёт', html)


def send_reset_email(to_email, name, raw_token):
    url = f'{settings.APP_BASE_URL}/reset-password?token={raw_token}'
    html = f"""
    <div style="font-family:Arial,Helvetica,sans-serif;max-width:560px;margin:auto;color:#222">
      <h2 style="color:#2855af">Восстановление пароля</h2>
      <p>Здравствуйте, {escape(name)}!</p>
      <p>Был получен запрос на восстановление пароля для вашего аккаунта в системе «Учёт».</p>
      <p>Чтобы задать новый пароль, нажмите кнопку ниже:</p>
      <p style="text-align:center;margin:32px 0">
        <a href="{url}"
           style="background:#2855af;color:#fff;text-decoration:none;
                  padding:12px 24px;border-radius:6px;display:inline-block;font-weight:600">
          Сбросить пароль
        </a>
      </p>
      <p style="font-size:13px;color:#666">Если кнопка не работает, скопируйте ссылку в браузер:<br>
        <a href="{url}">{url}</a>
      </p>
      <p style="font-size:13px;color:#666">Ссылка действительна {settings.RESET_TOKEN_TTL_HOURS} час. Если вы не запрашивали сброс пароля — просто проигнорируйте это письмо.</p>
    </div>"""
    _send_html_mail(to_email, 'Сброс пароля в системе Учёт', html)


def send_duplicate_registration_email(to_email, name):
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:560px;margin:auto;color:#222">
      <h2 style="color:#2855af">Здравствуйте, {escape(name)}!</h2>
      <p>Кто-то (возможно, вы) попытался зарегистрировать аккаунт на этот email в системе «Учёт».</p>
      <p>Ваша учётная запись уже создана и активна. Если вы забыли свой пароль, вы можете восстановить его по ссылке ниже:</p>
      <p style="text-align:center;margin:32px 0">
        <a href="{settings.APP_BASE_URL}/forgot-password" style="background:#2855af;color:#fff;text-decoration:none;padding:12px 24px;border-radius:6px;display:inline-block;font-weight:600">
          Восстановить пароль
        </a>
      </p>
      <p style="font-size:13px;color:#666">Если это были не вы, просто проигнорируйте это письмо.</p>
    </div>"""
    _send_html_mail(to_email, 'Попытка повторной регистрации в системе Учёт', html)


# ------------------- JWT / cookies -------------------
def issue_access_token(user):
    payload = {
        'userId': user.id,
        'email': user.email,
        'name': user.name,
        'exp': timezone.now() + timedelta(minutes=settings.JWT_ACCESS_TTL_MINUTES),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token):
    return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])


def compute_refresh_expiry(session_started_at):
    idle_deadline = timezone.now() + timedelta(minutes=settings.IDLE_TIMEOUT_MINUTES)
    absolute_deadline = session_started_at + timedelta(hours=settings.REFRESH_TTL_HOURS)
    return min(idle_deadline, absolute_deadline)


def set_refresh_cookie(response, raw_token, expires_at):
    max_age = max(0, int((expires_at - timezone.now()).total_seconds()))
    response.set_cookie(
        'refreshToken', raw_token,
        max_age=max_age,
        path='/api/refresh',
        httponly=True,
        secure=settings.USE_SECURE_COOKIE,
        samesite='Lax',
    )


def clear_refresh_cookie(response):
    response.delete_cookie('refreshToken', path='/api/refresh')


# ------------------- Rate limit (БД, общий для всех воркеров gunicorn) -------------------
def check_rate_limit(key: str, limit: int, window_seconds: int) -> bool:
    """
    Возвращает True, если запрос разрешён (и засчитывает попытку), False —
    если лимит исчерпан. `key` обычно 'register:<ip>' или 'login:<ip>'.
    """
    now = timezone.now()
    window_start = now - timedelta(seconds=window_seconds)
    RateLimitHit.objects.filter(key=key, created_at__lt=window_start).delete()
    count = RateLimitHit.objects.filter(key=key, created_at__gte=window_start).count()
    if count >= limit:
        return False
    RateLimitHit.objects.create(key=key)
    return True


def client_ip(request):
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', 'unknown')
