"""Аутентификация API по Access-токену модуля авторизации (Bearer JWT)."""
import jwt
from django.contrib.auth import get_user_model
from rest_framework import authentication, exceptions

from accounts.utils import decode_access_token


class JWTAuthentication(authentication.BaseAuthentication):
    keyword = 'Bearer'

    def authenticate(self, request):
        header = request.META.get('HTTP_AUTHORIZATION', '')
        if not header.startswith('Bearer '):
            return None
        token = header.split(' ', 1)[1].strip()
        try:
            payload = decode_access_token(token)
        except jwt.PyJWTError:
            raise exceptions.AuthenticationFailed('Токен недействителен или истёк')
        user = get_user_model().objects.filter(pk=payload.get('userId')).first()
        if user is None or user.status != user.STATUS_ACTIVE:
            raise exceptions.AuthenticationFailed('Пользователь недоступен')
        return user, payload

    def authenticate_header(self, request):
        return 'Bearer'
