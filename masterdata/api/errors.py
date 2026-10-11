"""Единый формат ошибок API: {ok:false, error, fields:{поле:[...]}}.
Ошибки валидации показываются в UI у конкретного поля (МД-15)."""
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models.deletion import ProtectedError
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_handler


def _flatten(detail):
    if isinstance(detail, dict):
        return {k: _flatten(v) for k, v in detail.items()}
    if isinstance(detail, list):
        out = []
        for d in detail:
            f = _flatten(d)
            if isinstance(f, list):
                out.extend(f)
            else:
                out.append(f)
        return out
    return str(detail)


def exception_handler(exc, context):
    if isinstance(exc, DjangoValidationError):
        exc = exceptions.ValidationError(exc.message_dict if hasattr(exc, 'error_dict') else exc.messages)
    if isinstance(exc, ProtectedError):
        return Response({'ok': False, 'error': 'На запись есть ссылки — её можно только архивировать'},
                        status=status.HTTP_409_CONFLICT)
    resp = drf_handler(exc, context)
    if resp is None:
        return None
    if isinstance(exc, exceptions.ValidationError):
        detail = _flatten(exc.detail)
        if isinstance(detail, dict):
            fields = {k: v for k, v in detail.items() if k != 'non_field_errors'}
            general = detail.get('non_field_errors') or []
            msg = '; '.join(general) or 'Проверьте заполнение полей'
            resp.data = {'ok': False, 'error': msg, 'fields': fields}
        else:
            resp.data = {'ok': False, 'error': '; '.join(detail) if isinstance(detail, list) else str(detail)}
    else:
        d = resp.data
        msg = d.get('detail') if isinstance(d, dict) else d
        if isinstance(exc, exceptions.NotAuthenticated):
            msg = 'Токен отсутствует'
        resp.data = {'ok': False, 'error': str(msg)}
    return resp
