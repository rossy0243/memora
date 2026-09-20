"""Visuels de marque Memora pour les reseaux sociaux (SVG maitres, rasterises ensuite en PNG).

Meme dessin que le site et le QR a imprimer : le monogramme (anneau + M) de
static/img/memora-mark.svg, le mot « Memora » en Fraunces Bold, le slogan en Cormorant
Garamond, sur l'encre de la charte (#241f22). Tout le texte est converti en courbes :
le rendu est identique partout, sans police a installer.
"""
from xml.sax.saxutils import escape

from .qr_kit import (
    BRAND_SLOGAN,
    _MARK_M,
    _MARK_RECTS,
    _MARK_RING,
    _font,
    _num,
    _svg_path,
)

INK = "#241f22"
CREAM = "#f4d9d5"  # « primary-soft » : la couleur du monogramme
GOLD = "#d8b46a"  # « champagne » : les petits ornements
WHITE = "#ffffff"

ICON_SIZE = 2048
LOGO_SIZE = (2400, 1200)
BANNER_SIZE = (3000, 1000)  # 3:1, le format d'en-tete X / LinkedIn / Facebook @2x


def _mark(x, y, size, color=CREAM):
    """Monogramme dans une boite carree de `size` (identique a memora-mark.svg, sans le carre sombre)."""
    ring = _MARK_RING
    rects = "".join(f'<rect x="{_num(rx)}" y="{_num(ry)}" width="{_num(rw)}" height="{_num(rh)}"/>' for rx, ry, rw, rh in _MARK_RECTS)
    return (
        f'<g transform="translate({_num(x)} {_num(y)}) scale({size / 64:.5f})" fill="{color}">'
        f'<g transform="translate(-1.23 -0.9) scale(0.329)">'
        f'<ellipse cx="{ring[0]}" cy="{ring[1]}" rx="{ring[2]}" ry="{ring[3]}" fill="none" stroke="{color}" stroke-width="{ring[4]}"/>'
        f'<path d="{_svg_path(_MARK_M)}"/>{rects}</g></g>'
    )


def _text(key, text, x, baseline, size, color, label=None):
    return f'<path fill="{color}" aria-label="{escape(label or text)}" d="{_svg_path(_font(key).outline(text, x, baseline, size))}"/>'


def _lockup(center_x, center_y, mark_size, word_size, gap):
    """Monogramme + « Memora », l'ensemble centre sur (center_x, center_y)."""
    word = "Memora"
    word_width = _font("wordmark").measure(word, word_size)
    total = mark_size + gap + word_width
    left = center_x - total / 2
    top = center_y - mark_size / 2
    parts = [
        _mark(left, top, mark_size),
        _text("wordmark", word, left + mark_size + gap, center_y + word_size * 0.32, word_size, WHITE),
    ]
    return "".join(parts)


def _svg(width, height, title, body, defs=""):
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        f'role="img" aria-label="{escape(title)}">\n<title>{escape(title)}</title>\n'
        f"{defs}{body}\n</svg>\n"
    )


def icon_svg():
    """Le monogramme seul, plein cadre : photo de profil (les reseaux la decoupent en cercle)."""
    size = ICON_SIZE
    mark = size * 0.88  # l'anneau occupe 70 % du cote : il reste entier dans le cercle de decoupe
    body = f'<rect width="{size}" height="{size}" fill="{INK}"/>\n' + _mark((size - mark) / 2, (size - mark) / 2, mark)
    return _svg(size, size, "Memora - monogramme", body)


def logo_svg():
    """Monogramme + « Memora », sur l'encre de la charte."""
    width, height = LOGO_SIZE
    body = f'<rect width="{width}" height="{height}" fill="{INK}"/>\n' + _lockup(width / 2, height / 2, 330, 270, 70)
    return _svg(width, height, "Memora", body)


def banner_svg():
    """Bandeau : monogramme + « Memora » + slogan. Le texte reste dans la bande centrale,
    donc lisible meme rogne en 4:1 (LinkedIn) ou en 2,6:1 (Facebook)."""
    width, height = BANNER_SIZE
    defs = (
        "<defs>"
        '<radialGradient id="glow" cx="50%" cy="46%" r="62%">'
        '<stop offset="0" stop-color="#342b30"/><stop offset="1" stop-color="' + INK + '"/>'
        "</radialGradient></defs>\n"
    )
    cx = width / 2
    slogan_size = 68
    slogan = BRAND_SLOGAN
    slogan_width = _font("slogan").measure(slogan, slogan_size)
    rule_y = 634
    body = (
        f'<rect width="{width}" height="{height}" fill="url(#glow)"/>\n'
        + _lockup(cx, 370, 250, 205, 56)
        + f'<rect x="{_num(cx - 170)}" y="{rule_y}" width="120" height="3" fill="{GOLD}"/>'
        + f'<rect x="{_num(cx + 50)}" y="{rule_y}" width="120" height="3" fill="{GOLD}"/>'
        + f'<path d="M{_num(cx)} {rule_y - 13}L{_num(cx + 14)} {rule_y + 1.5}L{_num(cx)} {rule_y + 16}L{_num(cx - 14)} {rule_y + 1.5}Z" fill="{GOLD}"/>'
        + _text("slogan", slogan, cx - slogan_width / 2, 752, slogan_size, CREAM)
    )
    return _svg(width, height, "Memora - Revivez votre événement à travers les yeux de vos invités", body, defs)


ASSETS = {
    "memora-logo-icone": (icon_svg, ICON_SIZE, ICON_SIZE),
    "memora-logo-nom": (logo_svg, *LOGO_SIZE),
    "memora-banniere": (banner_svg, *BANNER_SIZE),
}
