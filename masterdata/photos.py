"""Фото (МД-19, §8): загрузка, превью 300 и 1200 px, ссылки с ограниченным
сроком действия, раскладка ZIP-архива по моделям (МД-34)."""
import io
import os
import re
import time
import zipfile

from django.conf import settings
from django.core import signing
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction
from rest_framework.exceptions import ValidationError

from . import models as m

ALLOWED_EXT = {'.jpg', '.jpeg', '.png', '.webp', '.heic', '.heif'}
THUMB_SIZES = {'thumb_300': 300, 'thumb_1200': 1200}

try:  # HEIC/HEIF: если установлен pillow-heif — делаем превью и для них
    from pillow_heif import register_heif_opener  # type: ignore
    register_heif_opener()
    HEIF_OK = True
except Exception:  # pragma: no cover
    HEIF_OK = False


def _is_local_storage():
    return default_storage.__class__.__name__ in ('FileSystemStorage', 'InMemoryStorage')


def signed_url(photo, variant='file'):
    """Ссылка на фото, действительная MD_SIGNED_URL_TTL секунд.
    Для S3 — presigned URL самого хранилища; для локального диска —
    URL Django-вьюхи с подписью (картинку можно вставить в <img>)."""
    f = getattr(photo, variant)
    if not f:
        return ''
    if not _is_local_storage():
        return default_storage.url(f.name)
    exp = int(time.time()) + settings.MD_SIGNED_URL_TTL
    # округляем срок до 10 минут, чтобы ссылки кешировались браузером
    exp = exp - exp % 600 + 600
    sig = signing.Signer(salt='md-photo').signature(f'{photo.id}:{variant}:{exp}')
    return f'/api/md/photos/{photo.id}/{variant}?exp={exp}&sig={sig}'


def check_signature(photo_id, variant, exp, sig):
    try:
        exp = int(exp)
    except (TypeError, ValueError):
        return False
    if exp < time.time():
        return False
    expected = signing.Signer(salt='md-photo').signature(f'{photo_id}:{variant}:{exp}')
    return signing.constant_time_compare(expected, sig or '')


def _make_thumbs(photo, raw: bytes):
    try:
        from PIL import Image, ImageOps
        img = Image.open(io.BytesIO(raw))
        img = ImageOps.exif_transpose(img)
        if img.mode not in ('RGB', 'L'):
            img = img.convert('RGB')
    except Exception:
        return  # формат без поддержки превью (например, HEIC без pillow-heif)
    base = os.path.splitext(photo.original_name or 'photo')[0][:60]
    for field, px in THUMB_SIZES.items():
        im = img.copy()
        im.thumbnail((px, px))
        buf = io.BytesIO()
        im.save(buf, format='JPEG', quality=85, optimize=True)
        getattr(photo, field).save(f'{base}_{px}.jpg', ContentFile(buf.getvalue()), save=False)


def add_photo(org, user, raw: bytes, filename: str, *, product_model=None, item=None, record=None,
              photo_type=None, order=None, is_main=None):
    ext = os.path.splitext(filename or '')[1].lower()
    if ext not in ALLOWED_EXT:
        raise ValidationError({'file': [f'{filename}: допустимы JPG, PNG, WEBP, HEIC']})
    if len(raw) > settings.MD_PHOTO_MAX_BYTES:
        raise ValidationError({'file': [f'{filename}: файл больше 15 МБ']})
    owner = dict(product_model=product_model, item=item, record=record)
    existing = m.Photo.objects.filter(organization=org, **{k: v for k, v in owner.items() if v is not None})
    if order is None:
        order = (existing.order_by('-order').values_list('order', flat=True).first() or 0) + 1
    if is_main is None:
        is_main = not existing.filter(is_main=True).exists()
    with transaction.atomic():
        if is_main:
            existing.update(is_main=False)
        p = m.Photo(organization=org, created_by=user, original_name=filename[-255:], size_bytes=len(raw),
                    photo_type=photo_type, order=order, is_main=is_main, **owner)
        p.file.save(filename[-80:], ContentFile(raw), save=False)
        _make_thumbs(p, raw)
        p.save()
    return p


def delete_photo(photo):
    for f in (photo.file, photo.thumb_300, photo.thumb_1200):
        if f:
            try:
                f.delete(save=False)
            except Exception:
                pass
    owner = dict(product_model_id=photo.product_model_id, item_id=photo.item_id, record_id=photo.record_id)
    was_main = photo.is_main
    photo.delete()
    if was_main:
        nxt = m.Photo.objects.filter(**owner).order_by('order').first()
        if nxt:
            nxt.is_main = True
            nxt.save(update_fields=['is_main'])


NAME_RE = re.compile(r'^(?P<key>.+?)(?:[_\s](?P<n>\d{1,3}))?$')


def import_zip(org, user, raw: bytes):
    """МД-34: имя файла — артикул модели или бирка экземпляра с порядковым
    номером (СВ-117_1.jpg, СВ-117_2.jpg, 000123_1.jpg)."""
    report = {'added': 0, 'skipped': [], 'models': {}, 'items': {}}
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        raise ValidationError({'file': ['Файл не является ZIP-архивом']})
    names = sorted(n for n in zf.namelist() if not n.endswith('/') and '__MACOSX' not in n)
    for name in names:
        base = os.path.basename(name)
        stem, ext = os.path.splitext(base)
        if ext.lower() not in ALLOWED_EXT:
            report['skipped'].append({'file': base, 'reason': 'Неподдерживаемый формат'})
            continue
        mt = NAME_RE.match(stem.strip())
        key, n = mt.group('key'), int(mt.group('n') or 0)
        model = m.ProductModel.objects.filter(organization=org, article__iexact=key).first()
        item = None if model else m.Item.objects.filter(organization=org, tag=key).first()
        if model is None and item is None:
            # СВ-117-44_1 — артикул экземпляра → модель СВ-117
            mm = re.match(r'^(.+)-([^-]+)$', key)
            if mm:
                model = m.ProductModel.objects.filter(organization=org, article__iexact=mm.group(1)).first()
        if model is None and item is None:
            report['skipped'].append({'file': base, 'reason': f'Не найдена модель или бирка «{key}»'})
            continue
        data = zf.read(name)
        try:
            add_photo(org, user, data, base, product_model=model, item=item, order=n or None,
                      is_main=True if n == 1 else None)
        except ValidationError as e:
            report['skipped'].append({'file': base, 'reason': '; '.join(e.detail.get('file', ['Ошибка']))})
            continue
        report['added'] += 1
        bucket = report['models'] if model else report['items']
        k = model.article if model else item.tag
        bucket[k] = bucket.get(k, 0) + 1
    return report
