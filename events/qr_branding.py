"""QR code d'evenement « pret a imprimer » : le QR, puis en petit la marque Memora.

Le QR lui-meme (voir services.build_event_qr_code_png) reste intact et en grand :
la marque ne vit qu'en dessous, sur le meme fond, pour ne jamais gener la lecture.
Style epure : logo, slogan, filet dore, une ligne de contact.
"""
from io import BytesIO
from pathlib import Path

import qrcode
from django.conf import settings
from PIL import Image, ImageDraw, ImageFont

BRAND_SLOGAN = "Revivez votre événement à travers les yeux de vos invités."

_BACKGROUND = "#fffaf7"
_INK = "#241f22"
_MUTED = "#6f646a"
_GOLD = "#d8b46a"

_FONT_DIR = Path(settings.BASE_DIR) / "remotion" / "public" / "fonts"
_MARK_PATH = Path(settings.BASE_DIR) / "static" / "img" / "memora-mark-print.png"


def brand_contact_items(site_configuration):
    """Adresse du site, e-mail et WhatsApp de Memora, ceux qui sont renseignes."""
    site_url = (settings.MEMORA_PUBLIC_BASE_URL or "").strip()
    host = site_url.split("://", 1)[-1].strip("/")
    items = [host] if host else []
    email = site_configuration.effective_support_email
    if email:
        items.append(email)
    whatsapp = (site_configuration.support_whatsapp or "").strip()
    if whatsapp:
        items.append(f"WhatsApp {whatsapp}")
    return items


def _font(name, size, weight=None, optical_size=None):
    """Police variable Memora (Fraunces / Cormorant) au poids voulu."""
    try:
        font = ImageFont.truetype(str(_FONT_DIR / name), size)
    except OSError:
        # Police absente : Pillow embarque une police par defaut, moins belle mais lisible.
        return ImageFont.load_default(size=size)
    try:
        values = []
        for axis in font.get_variation_axes():
            label = axis["name"].decode() if isinstance(axis["name"], bytes) else axis["name"]
            value = axis["default"]
            if label == "Weight" and weight is not None:
                value = weight
            elif label == "Optical Size" and optical_size is not None:
                value = optical_size
            values.append(max(axis["minimum"], min(value, axis["maximum"])))
        font.set_variation_by_axes(values)
    except (OSError, ValueError, AttributeError):
        pass
    return font


def _text_width(draw, text, font):
    left, _, right, _ = draw.textbbox((0, 0), text, font=font)
    return right - left


def _fit_lines(draw, items, font, max_width, separator="  ·  "):
    """Regroupe les elements de contact sur le moins de lignes possible."""
    lines, current = [], ""
    for item in items:
        candidate = item if not current else f"{current}{separator}{item}"
        if current and _text_width(draw, candidate, font) > max_width:
            lines.append(current)
            current = item
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def build_branded_qr_png(public_url, site_configuration):
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=20,
        border=2,
    )
    qr.add_data(public_url)
    qr.make(fit=True)
    code = qr.make_image(fill_color=_INK, back_color=_BACKGROUND).convert("RGB")

    margin = 90
    width = code.width + 2 * margin
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))

    wordmark_font = _font("Fraunces-VF.ttf", 60, weight=700, optical_size=72)
    slogan_font = _font("CormorantGaramond-VF.ttf", 35, weight=500)
    contact_font = _font("CormorantGaramond-VF.ttf", 34, weight=600)

    slogan_lines = _fit_lines(probe, BRAND_SLOGAN.split(" "), slogan_font, width - 2 * margin, separator=" ")
    contact_lines = _fit_lines(probe, brand_contact_items(site_configuration), contact_font, width - 2 * margin)

    mark_size = 84
    gap = 26
    footer_height = (
        mark_size
        + gap
        + len(slogan_lines) * 52
        + gap
        + 4
        + gap
        + len(contact_lines) * 48
    )
    height = margin + code.height + 60 + footer_height + margin

    canvas = Image.new("RGB", (width, height), _BACKGROUND)
    canvas.paste(code, (margin, margin))
    draw = ImageDraw.Draw(canvas)

    y = margin + code.height + 60
    word = "Memora"
    word_width = _text_width(draw, word, wordmark_font)
    group_width = mark_size + 22 + word_width
    x = (width - group_width) // 2
    if _MARK_PATH.exists():
        mark = Image.open(_MARK_PATH).convert("RGBA").resize((mark_size, mark_size), Image.LANCZOS)
        canvas.paste(mark, (x, y), mark)
    draw.text((x + mark_size + 22, y + mark_size // 2), word, font=wordmark_font, fill=_INK, anchor="lm")
    y += mark_size + gap

    for line in slogan_lines:
        draw.text((width // 2, y), line, font=slogan_font, fill=_MUTED, anchor="mt")
        y += 52
    y += gap
    draw.rectangle((width // 2 - 60, y, width // 2 + 60, y + 3), fill=_GOLD)
    y += 4 + gap
    for line in contact_lines:
        draw.text((width // 2, y), line, font=contact_font, fill=_INK, anchor="mt")
        y += 48

    buffer = BytesIO()
    canvas.save(buffer, format="PNG", optimize=True, dpi=(300, 300))
    return buffer.getvalue()
