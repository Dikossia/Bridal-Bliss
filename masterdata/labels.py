"""Печать ярлыков (МД-17): PDF 58×40 мм — бирка, артикул, наименование,
размер и QR-код. По одному или пачкой (одна страница — один ярлык)."""
import io
import os

from reportlab.graphics import renderPDF
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

FONT_DIR = os.path.join(os.path.dirname(__file__), 'fonts')
_REGISTERED = False
W, H = 58 * mm, 40 * mm


def _fonts():
    global _REGISTERED
    if not _REGISTERED:
        pdfmetrics.registerFont(TTFont('DejaVu', os.path.join(FONT_DIR, 'DejaVuSans.ttf')))
        pdfmetrics.registerFont(TTFont('DejaVu-Bold', os.path.join(FONT_DIR, 'DejaVuSans-Bold.ttf')))
        _REGISTERED = True


def _fit(c, text, font, size, max_w):
    while size > 5 and pdfmetrics.stringWidth(text, font, size) > max_w:
        size -= 0.5
    if pdfmetrics.stringWidth(text, font, size) > max_w:
        while text and pdfmetrics.stringWidth(text + '…', font, size) > max_w:
            text = text[:-1]
        text += '…'
    return text, size


def qr_payload(item, base_url=''):
    # QR ведёт на карточку экземпляра; сканер на кассе может читать и просто бирку.
    return f'{base_url}/md#/d/items/{item.pk}' if base_url else item.tag


def render_labels(items, base_url=''):
    _fonts()
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(W, H))
    c.setTitle('Ярлыки')
    for it in items:
        pad = 2.5 * mm
        qr_size = 22 * mm
        # QR справа
        w = QrCodeWidget(qr_payload(it, base_url))
        w.barLevel = 'M'
        b = w.getBounds()
        bw, bh = b[2] - b[0], b[3] - b[1]
        d = Drawing(qr_size, qr_size, transform=[qr_size / bw, 0, 0, qr_size / bh, 0, 0])
        d.add(w)
        renderPDF.draw(d, c, W - qr_size - pad + 1 * mm, H - qr_size - pad)
        text_w = W - qr_size - 2 * pad
        # Бирка — крупно
        t, s = _fit(c, it.tag, 'DejaVu-Bold', 15, text_w)
        c.setFont('DejaVu-Bold', s)
        c.drawString(pad, H - pad - 5 * mm, t)
        # Артикул экземпляра
        t, s = _fit(c, it.article, 'DejaVu-Bold', 10, text_w)
        c.setFont('DejaVu-Bold', s)
        c.drawString(pad, H - pad - 10.5 * mm, t)
        # Размер
        if it.size_id:
            c.setFont('DejaVu', 8)
            c.drawString(pad, H - pad - 15 * mm, f'Размер: {it.size}')
        # Наименование — внизу на всю ширину
        name = it.model.name
        t, s = _fit(c, name, 'DejaVu', 8, W - 2 * pad)
        c.setFont('DejaVu', s)
        c.drawString(pad, pad + 3.2 * mm, t)
        c.setFont('DejaVu', 6)
        c.drawString(pad, pad, (it.salon.name if it.salon_id else '')[:40])
        c.showPage()
    c.save()
    return buf.getvalue()
