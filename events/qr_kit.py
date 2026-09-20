"""Pack QR code « pret a poser » d'un evenement, pour tout support imprime ou affiche.

Un seul dessin exact (le QR en grand, une phrase d'invitation au-dessus, la marque
Memora en petit dessous), rendu en SVG, PDF et PNG, sur FOND TRANSPARENT : c'est le
support (chevalet, affiche, bache, ecran) qui donne la couleur. Deux versions, QR
noir pour les fonds clairs et QR blanc pour les fonds fonces ; trois mises en page
(portrait, paysage 16:9, carre).

Qualite d'impression :
  - SVG et PDF sont VECTORIELS, le texte est converti en courbes : net a n'importe
    quelle taille (bache de 2 m comprise) et aucune police a installer chez
    l'imprimeur ;
  - le PDF utilise le noir « pur » (K seul), celui que les imprimeurs attendent ;
  - le QR est en correction d'erreur Q (25 %) : il reste lisible s'il est tache,
    plie ou use.
"""
import io
import math
import re
import zipfile
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape

import qrcode
from django.conf import settings
from fontTools.pens.basePen import BasePen
from fontTools.ttLib import TTFont
from PIL import Image, ImageChops, ImageDraw, ImageFont

BRAND_SLOGAN = "Revivez votre événement à travers les yeux de vos invités."
PHRASE = "Scannez pour partager vos souvenirs"

_ASSETS = Path(__file__).resolve().parent / "qr_assets"
_FONT_FILES = {
    "phrase": "CormorantGaramond-SemiBold.ttf",
    "wordmark": "Fraunces-Bold.ttf",
    "slogan": "CormorantGaramond-Medium.ttf",
    "contact": "CormorantGaramond-SemiBold.ttf",
}

COLORS = {
    # nom du dossier : (rvb, encre CMJN « K » du PDF, fond plein du PNG, libelle du fond)
    "noir-pour-fonds-clairs": ((0, 0, 0), 1.0, (255, 255, 255), "fond-blanc"),
    "blanc-pour-fonds-fonces": ((255, 255, 255), 0.0, (0, 0, 0), "fond-noir"),
}


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
        items.append(f"WhatsApp {_format_phone(whatsapp)}")
    return items


def _format_phone(number):
    """+243842616570 -> +243 842 616 570 (un numero deja espace est laisse tel quel)."""
    match = re.fullmatch(r"\+243(\d{3})(\d{3})(\d{3})", number)
    return f"+243 {match.group(1)} {match.group(2)} {match.group(3)}" if match else number


# --- QR ---------------------------------------------------------------------------


def qr_matrix(url):
    qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_Q, box_size=1, border=0)
    qr.add_data(url)
    qr.make(fit=True)
    return qr.get_matrix()


def qr_runs(matrix):
    """Modules sombres regroupes en segments horizontaux : (colonne, ligne, longueur)."""
    runs = []
    for row, line in enumerate(matrix):
        col = 0
        while col < len(line):
            if line[col]:
                start = col
                while col < len(line) and line[col]:
                    col += 1
                runs.append((start, row, col - start))
            else:
                col += 1
    return runs


# --- Polices : contours vectoriels --------------------------------------------------


class _OutlinePen(BasePen):
    """Contours d'un glyphe en segments M/L/C (les courbes TrueType sont converties)."""

    def __init__(self, glyph_set):
        super().__init__(glyph_set)
        self.ops = []

    def _moveTo(self, pt):
        self.ops.append(("M", pt))

    def _lineTo(self, pt):
        self.ops.append(("L", pt))

    def _curveToOne(self, p1, p2, p3):
        self.ops.append(("C", p1, p2, p3))

    def _qCurveToOne(self, p1, p2):
        p0 = self._getCurrentPoint()
        c1 = (p0[0] + 2 / 3 * (p1[0] - p0[0]), p0[1] + 2 / 3 * (p1[1] - p0[1]))
        c2 = (p2[0] + 2 / 3 * (p1[0] - p2[0]), p2[1] + 2 / 3 * (p1[1] - p2[1]))
        self.ops.append(("C", c1, c2, p2))

    def _closePath(self):
        self.ops.append(("Z",))


class OutlineFont:
    def __init__(self, filename):
        self.path = _ASSETS / filename
        self.font = TTFont(self.path)
        self.upem = self.font["head"].unitsPerEm
        self.cmap = self.font.getBestCmap()
        self.metrics = self.font["hmtx"].metrics
        self.glyph_set = self.font.getGlyphSet()
        self._cache = {}

    def _glyph(self, char):
        name = self.cmap.get(ord(char)) or ".notdef"
        if name not in self._cache:
            pen = _OutlinePen(self.glyph_set)
            self.glyph_set[name].draw(pen)
            self._cache[name] = (self.metrics[name][0], pen.ops)
        return self._cache[name]

    def measure(self, text, size):
        return sum(self._glyph(char)[0] for char in text) * size / self.upem

    def outline(self, text, x, baseline, size):
        """Contours du texte, en coordonnees de mise en page (l'axe y descend)."""
        scale = size / self.upem
        pen_x = x
        ops = []
        for char in text:
            advance, glyph_ops = self._glyph(char)
            for op in glyph_ops:
                ops.append((op[0], *[(pen_x + px * scale, baseline - py * scale) for px, py in op[1:]]))
            pen_x += advance * scale
        return ops


_FONTS = {}


def _font(key):
    if key not in _FONTS:
        _FONTS[key] = OutlineFont(_FONT_FILES[key])
    return _FONTS[key]


def _pil_font(key, size_px):
    # Mise en page BASIC : pas de crenage GPOS, donc exactement les memes largeurs
    # que les contours du SVG et du PDF.
    return ImageFont.truetype(str(_ASSETS / _FONT_FILES[key]), max(int(round(size_px)), 1), layout_engine=ImageFont.Layout.BASIC)


# --- Logo (marque monochrome : anneau + M, sans fond) ---------------------------------

_MARK_RING = (101, 100, 78, 80, 9)  # cx, cy, rx, ry, epaisseur (espace de dessin du logo)
_MARK_M = [
    ("M", (46, 62)),
    ("C", (44.5, 86), (43.2, 112), (43, 138)),
    ("L", (49, 138)),
    ("C", (51, 112), (54.5, 90), (57, 71)),
    ("L", (95, 133)),
    ("L", (101, 141)),
    ("L", (139, 70)),
    ("C", (141, 92), (144.8, 116), (146, 138)),
    ("L", (159, 138)),
    ("C", (159.2, 112), (157.8, 86), (156, 62)),
    ("L", (133, 62)),
    ("L", (105, 121)),
    ("L", (71, 62)),
    ("Z",),
]
_MARK_RECTS = [(38.5, 59, 36, 3), (129.5, 59, 34, 3), (34, 135.5, 24, 3), (140, 135.5, 25, 3)]


def _mark_point(x, y, size):
    """Transformation du logo (identique a memora-mark.svg) vers la mise en page."""
    unit = size / 64
    return lambda px, py: (x + unit * (px * 0.329 - 1.23), y + unit * (py * 0.329 - 0.9))


def _ellipse_ops(cx, cy, rx, ry):
    kappa = 0.5522847498
    ox, oy = rx * kappa, ry * kappa
    return [
        ("M", (cx + rx, cy)),
        ("C", (cx + rx, cy + oy), (cx + ox, cy + ry), (cx, cy + ry)),
        ("C", (cx - ox, cy + ry), (cx - rx, cy + oy), (cx - rx, cy)),
        ("C", (cx - rx, cy - oy), (cx - ox, cy - ry), (cx, cy - ry)),
        ("C", (cx + ox, cy - ry), (cx + rx, cy - oy), (cx + rx, cy)),
        ("Z",),
    ]


def _transform_ops(ops, transform):
    return [(op[0], *[transform(*point) for point in op[1:]]) for op in ops]


def _flatten(ops, steps=24):
    """Contours (M/L/C/Z) -> liste de polygones, pour le rendu PNG."""
    polygons, current = [], []
    for op in ops:
        if op[0] == "M":
            if current:
                polygons.append(current)
            current = [op[1]]
        elif op[0] == "L":
            current.append(op[1])
        elif op[0] == "C":
            (x0, y0), (x1, y1), (x2, y2), (x3, y3) = current[-1], op[1], op[2], op[3]
            for i in range(1, steps + 1):
                t = i / steps
                u = 1 - t
                current.append(
                    (
                        u**3 * x0 + 3 * u * u * t * x1 + 3 * u * t * t * x2 + t**3 * x3,
                        u**3 * y0 + 3 * u * u * t * y1 + 3 * u * t * t * y2 + t**3 * y3,
                    )
                )
    if current:
        polygons.append(current)
    return polygons


# --- Mise en page ---------------------------------------------------------------------


@dataclass
class Layout:
    name: str
    width: float
    height: float
    page_width_mm: float
    png_width: int
    items: list = field(default_factory=list)

    @property
    def page_height_mm(self):
        return self.page_width_mm * self.height / self.width


def _text(layout, key, text, size, x, baseline, anchor="middle"):
    width = _font(key).measure(text, size)
    left = x - width / 2 if anchor == "middle" else x
    layout.items.append(("text", key, text, size, left, baseline))
    return width


def _wrap(key, size, words, max_width, separator=" "):
    lines, current = [], ""
    for word in words:
        candidate = word if not current else f"{current}{separator}{word}"
        if current and _font(key).measure(candidate, size) > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def _brand_block(layout, y, *, center_x=None, left_x=None, max_width, scale, contacts):
    """Logo + « Memora », slogan, filet, contact. Renvoie l'ordonnee du bas du bloc."""
    mark = 66 * scale
    word_size = 52 * scale
    slogan_size = 30 * scale
    contact_size = 28 * scale
    word = "Memora"
    word_width = _font("wordmark").measure(word, word_size)
    group = mark + 16 * scale + word_width
    x0 = center_x - group / 2 if center_x is not None else left_x
    layout.items.append(("mark", x0, y, mark))
    _text(layout, "wordmark", word, word_size, x0 + mark + 16 * scale, y + mark / 2 + word_size * 0.32, anchor="start")
    y += mark + 40 * scale

    for line in _wrap("slogan", slogan_size, BRAND_SLOGAN.split(" "), max_width):
        if center_x is not None:
            _text(layout, "slogan", line, slogan_size, center_x, y)
        else:
            _text(layout, "slogan", line, slogan_size, left_x, y, anchor="start")
        y += slogan_size * 1.3
    y += 4 * scale
    rule_w = 100 * scale
    layout.items.append(("rect", (center_x - rule_w / 2) if center_x is not None else left_x, y, rule_w, max(3 * scale, 2)))
    y += 42 * scale

    contact_lines = _wrap("contact", contact_size, contacts, max_width, separator="  ·  ") if contacts else []
    for line in contact_lines:
        if center_x is not None:
            _text(layout, "contact", line, contact_size, center_x, y)
        else:
            _text(layout, "contact", line, contact_size, left_x, y, anchor="start")
        y += contact_size * 1.3
    return y - (contact_size * 1.3 if contact_lines else 0)


def _center_vertically(layout, top, bottom, margin_top=0):
    """Recentre verticalement le contenu dans la page (le fond etant transparent)."""
    offset = (layout.height - (bottom - top)) / 2 - top
    shifted = []
    for item in layout.items:
        kind = item[0]
        if kind == "qr":
            shifted.append((kind, item[1], item[2] + offset, item[3]))
        elif kind == "text":
            shifted.append((kind, item[1], item[2], item[3], item[4], item[5] + offset))
        elif kind == "mark":
            shifted.append((kind, item[1], item[2] + offset, item[3]))
        else:
            shifted.append((kind, item[1], item[2] + offset, item[3], item[4]))
    layout.items = shifted


def _stack_layout(name, width, height, page_mm, png_width, matrix, contacts, *, qr_size, phrase_lines, phrase_size, scale, margin):
    """Mise en page verticale, centree : phrase, QR, marque."""
    layout = Layout(name, width, height, page_mm, png_width)
    n = len(matrix)
    module = qr_size / n
    gap = max(56 * scale, 4.2 * module)  # zone de silence du QR : jamais de texte collé
    y = 0.0
    baseline = phrase_size * 0.72
    for line in phrase_lines:
        _text(layout, "phrase", line, phrase_size, width / 2, y + baseline)
        y += phrase_size * 1.14
    qr_top = y - phrase_size * 0.14 + gap - phrase_size * 0.02
    layout.items.append(("qr", (width - qr_size) / 2, qr_top, qr_size))
    brand_top = qr_top + qr_size + gap
    bottom = _brand_block(layout, brand_top, center_x=width / 2, max_width=width - 2 * margin, scale=scale, contacts=contacts)
    _center_vertically(layout, 0, bottom + 28 * scale)
    return layout, (bottom + 28 * scale)


def portrait_layout(matrix, contacts):
    for qr_size in range(700, 400, -4):
        layout, needed = _stack_layout(
            "portrait", 1000, 1414.2857, 210, 3000, matrix, contacts,
            qr_size=qr_size, phrase_lines=["Scannez pour partager", "vos souvenirs"], phrase_size=74, scale=1.0, margin=90,
        )
        if needed <= 1414.2857 - 140:
            return layout
    return layout


def square_layout(matrix, contacts):
    for qr_size in range(620, 300, -4):
        layout, needed = _stack_layout(
            "carre", 1000, 1000, 210, 3000, matrix, contacts,
            qr_size=qr_size, phrase_lines=[PHRASE], phrase_size=52, scale=0.78, margin=70,
        )
        if needed <= 1000 - 110:
            return layout
    return layout


def landscape_layout(matrix, contacts):
    layout = Layout("paysage-16x9", 1920, 1080, 297, 3840)
    qr_size = 820
    layout.items.append(("qr", 150, (1080 - qr_size) / 2, qr_size))
    left = 1080
    max_width = 1920 - 90 - left
    size = 104
    y = 0.0
    for line in ["Scannez pour", "partager", "vos souvenirs"]:
        _text(layout, "phrase", line, size, left, y + size * 0.72, anchor="start")
        y += size * 1.12
    brand_top = y + 56
    bottom = _brand_block(layout, brand_top, left_x=left, max_width=max_width, scale=1.05, contacts=contacts)
    total = bottom + 30
    offset = (1080 - total) / 2
    shifted = []
    for item in layout.items:
        kind = item[0]
        if kind == "qr":
            shifted.append(item)
        elif kind == "text":
            shifted.append((kind, item[1], item[2], item[3], item[4], item[5] + offset))
        elif kind == "mark":
            shifted.append((kind, item[1], item[2] + offset, item[3]))
        else:
            shifted.append((kind, item[1], item[2] + offset, item[3], item[4]))
    layout.items = shifted
    return layout


LAYOUTS = (portrait_layout, landscape_layout, square_layout)


# --- Rendu SVG ------------------------------------------------------------------------


def _num(value):
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text if text not in ("", "-0") else "0"


def _svg_path(ops):
    parts = []
    for op in ops:
        if op[0] == "M":
            parts.append(f"M{_num(op[1][0])} {_num(op[1][1])}")
        elif op[0] == "L":
            parts.append(f"L{_num(op[1][0])} {_num(op[1][1])}")
        elif op[0] == "C":
            parts.append("C" + " ".join(f"{_num(px)} {_num(py)}" for px, py in op[1:]))
        else:
            parts.append("Z")
    return "".join(parts)


def render_svg(layout, matrix, color_hex, title):
    n = len(matrix)
    body = []
    for item in layout.items:
        kind = item[0]
        if kind == "qr":
            _, x, y, size = item
            unit = size / n
            d = "".join(
                f"M{_num(x + col * unit)} {_num(y + row * unit)}h{_num(run * unit)}v{_num(unit)}h-{_num(run * unit)}z"
                for col, row, run in qr_runs(matrix)
            )
            body.append(f'<path id="qr" d="{d}"/>')
        elif kind == "text":
            _, key, text, size, x, baseline = item
            body.append(f'<path aria-label="{escape(text)}" d="{_svg_path(_font(key).outline(text, x, baseline, size))}"/>')
        elif kind == "mark":
            _, x, y, size = item
            unit = size / 64
            ring = _MARK_RING
            rects = "".join(f'<rect x="{_num(rx)}" y="{_num(ry)}" width="{_num(rw)}" height="{_num(rh)}"/>' for rx, ry, rw, rh in _MARK_RECTS)
            body.append(
                f'<g id="logo" transform="translate({_num(x)} {_num(y)}) scale({unit:.5f})">'
                f'<g transform="translate(-1.23 -0.9) scale(0.329)">'
                f'<ellipse cx="{ring[0]}" cy="{ring[1]}" rx="{ring[2]}" ry="{ring[3]}" fill="none" stroke="{color_hex}" stroke-width="{ring[4]}"/>'
                f'<path d="{_svg_path(_MARK_M)}"/>{rects}</g></g>'
            )
        else:
            _, x, y, w, h = item
            body.append(f'<rect x="{_num(x)}" y="{_num(y)}" width="{_num(w)}" height="{_num(h)}"/>')
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {_num(layout.width)} {_num(layout.height)}" '
        f'width="{_num(layout.page_width_mm)}mm" height="{_num(layout.page_height_mm)}mm" role="img" aria-label="{escape(title)}">\n'
        f"<title>{escape(title)}</title>\n"
        f'<g fill="{color_hex}" shape-rendering="geometricPrecision">\n' + "\n".join(body) + "\n</g>\n</svg>\n"
    )


# --- Rendu PDF (vectoriel, noir « K » pour l'imprimeur) --------------------------------


def render_pdf(layout, matrix, ink_k, title):
    page_w = layout.page_width_mm * 72 / 25.4
    k = page_w / layout.width
    page_h = layout.height * k
    n = len(matrix)

    def px(x):
        return f"{x * k:.3f}"

    def py(y):
        return f"{page_h - y * k:.3f}"

    def path(ops):
        out = []
        for op in ops:
            if op[0] == "M":
                out.append(f"{px(op[1][0])} {py(op[1][1])} m")
            elif op[0] == "L":
                out.append(f"{px(op[1][0])} {py(op[1][1])} l")
            elif op[0] == "C":
                out.append(" ".join(f"{px(a)} {py(b)}" for a, b in op[1:]) + " c")
            else:
                out.append("h")
        return "\n".join(out)

    stream = [f"0 0 0 {ink_k:g} k", f"0 0 0 {ink_k:g} K"]
    for item in layout.items:
        kind = item[0]
        if kind == "qr":
            _, x, y, size = item
            unit = size / n
            for col, row, run in qr_runs(matrix):
                stream.append(f"{px(x + col * unit)} {py(y + (row + 1) * unit)} {run * unit * k:.3f} {unit * k:.3f} re")
            stream.append("f")
        elif kind == "text":
            _, key, text, size, x, baseline = item
            stream.append(path(_font(key).outline(text, x, baseline, size)))
            stream.append("f")
        elif kind == "mark":
            _, x, y, size = item
            transform = _mark_point(x, y, size)
            unit = size / 64 * 0.329
            cx, cy, rx, ry, stroke = _MARK_RING
            stream.append(f"{stroke * unit * k:.3f} w")
            stream.append(path(_transform_ops(_ellipse_ops(cx, cy, rx, ry), transform)))
            stream.append("S")
            stream.append(path(_transform_ops(_MARK_M, transform)))
            stream.append("f")
            for rx0, ry0, rw, rh in _MARK_RECTS:
                x0, y0 = transform(rx0, ry0)
                stream.append(f"{px(x0)} {py(y0 + rh * unit)} {rw * unit * k:.3f} {rh * unit * k:.3f} re")
            stream.append("f")
        else:
            _, x, y, w, h = item
            stream.append(f"{px(x)} {py(y + h)} {w * k:.3f} {h * k:.3f} re")
            stream.append("f")

    content = zlib.compress("\n".join(stream).encode("ascii"))
    safe_title = re.sub(r"[()\\]", "", title)
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page_w:.3f} {page_h:.3f}] "
            f"/Contents 4 0 R /Resources << >> >>"
        ).encode("ascii"),
        b"<< /Length " + str(len(content)).encode() + b" /Filter /FlateDecode >>\nstream\n" + content + b"\nendstream",
        f"<< /Title ({safe_title}) /Producer (Memora) >>".encode("latin-1", "replace"),
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{number} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        out.write(f"{offset:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R /Info 5 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


# --- Rendu PNG -------------------------------------------------------------------------


def _draw_mark(mask, x, y, size):
    supersample = 4
    box = int(math.ceil(size)) + 4
    frac_x, frac_y = x - math.floor(x), y - math.floor(y)
    local = Image.new("L", (box * supersample, box * supersample), 0)
    draw = ImageDraw.Draw(local)
    transform = _mark_point((frac_x + 1) * supersample, (frac_y + 1) * supersample, size * supersample)
    unit = size * supersample / 64 * 0.329
    cx, cy, rx, ry, stroke = _MARK_RING
    for radius_x, radius_y, fill in ((rx + stroke / 2, ry + stroke / 2, 255), (rx - stroke / 2, ry - stroke / 2, 0)):
        left, top = transform(cx - radius_x, cy - radius_y)
        right, bottom = transform(cx + radius_x, cy + radius_y)
        draw.ellipse([left, top, right, bottom], fill=fill)
    for polygon in _flatten(_transform_ops(_MARK_M, transform)):
        draw.polygon(polygon, fill=255)
    for rx0, ry0, rw, rh in _MARK_RECTS:
        x0, y0 = transform(rx0, ry0)
        draw.rectangle([x0, y0, x0 + rw * unit, y0 + rh * unit], fill=255)
    small = local.resize((box, box), Image.LANCZOS)
    ox, oy = int(math.floor(x)) - 1, int(math.floor(y)) - 1
    region = mask.crop((ox, oy, ox + box, oy + box))
    mask.paste(ImageChops.lighter(region, small), (ox, oy))


def render_mask(layout, matrix, width_px=None):
    """Silhouette du dessin (255 = encre) : la meme pour le noir et le blanc."""
    width_px = width_px or layout.png_width
    k = width_px / layout.width
    height_px = round(layout.height * k)
    mask = Image.new("L", (width_px, height_px), 0)
    draw = ImageDraw.Draw(mask)
    n = len(matrix)
    for item in layout.items:
        kind = item[0]
        if kind == "qr":
            _, x, y, size = item
            unit = size / n
            for col, row, run in qr_runs(matrix):
                x0, x1 = round((x + col * unit) * k), round((x + (col + run) * unit) * k)
                y0, y1 = round((y + row * unit) * k), round((y + (row + 1) * unit) * k)
                draw.rectangle([x0, y0, x1 - 1, y1 - 1], fill=255)
        elif kind == "text":
            _, key, text, size, x, baseline = item
            draw.text((x * k, baseline * k), text, font=_pil_font(key, size * k), fill=255, anchor="ls")
        elif kind == "mark":
            _, x, y, size = item
            _draw_mark(mask, x * k, y * k, size * k)
        else:
            _, x, y, w, h = item
            draw.rectangle([round(x * k), round(y * k), round((x + w) * k) - 1, max(round((y + h) * k) - 1, round(y * k))], fill=255)
    return mask


def png_from_mask(mask, color_rgb, background=None):
    """PNG transparent (background=None) ou sur fond plein, depuis la silhouette."""
    buffer = io.BytesIO()
    if background is None:
        channels = [Image.new("L", mask.size, value) for value in color_rgb]
        Image.merge("RGBA", (*channels, mask)).save(buffer, format="PNG", compress_level=6, dpi=(300, 300))
    else:
        image = Image.new("RGB", mask.size, background)
        image.paste(color_rgb, mask=mask)
        image.save(buffer, format="PNG", compress_level=6, dpi=(300, 300))
    return buffer.getvalue()


def build_preview_png(public_url, site_configuration, width_px=900):
    """Apercu du dashboard : la mise en page portrait, en noir sur fond blanc."""
    matrix = qr_matrix(public_url)
    layout = portrait_layout(matrix, brand_contact_items(site_configuration))
    return png_from_mask(render_mask(layout, matrix, width_px), (0, 0, 0), (255, 255, 255))


# --- Le ZIP -----------------------------------------------------------------------------

_README = """MEMORA - VOTRE QR CODE, PRET A POSER SUR TOUT SUPPORT
======================================================

Ce dossier contient le QR code de votre evenement, en grand, avec une phrase
d'invitation et la marque Memora en petit. Le fond est TRANSPARENT : c'est votre
support (chevalet, affiche, bache, ecran) qui donne la couleur.

CHOISIR NOIR OU BLANC
  noir-pour-fonds-clairs/   QR noir  -> papier blanc, fonds clairs ou pastel.
  blanc-pour-fonds-fonces/  QR blanc -> fonds sombres (noir, bordeaux, bleu nuit...).

CHOISIR LA MISE EN PAGE (dans chaque dossier)
  portrait/        Chevalet de table, affiche, menu, kakemono, bache verticale.
  paysage-16x9/    Ecran, television, projection, banniere horizontale.
  carre/           Reseaux sociaux, story, WhatsApp, cadre carre.

CHOISIR LE FICHIER
  .svg   Vectoriel : net a n'importe quelle taille, modifiable par un graphiste.
         A privilegier pour une bache, un kakemono ou un backdrop.
  .pdf   Vectoriel, pret a imprimer (noir pur pour l'imprimeur). A4 en portrait
         et en carre, 297 mm en paysage ; agrandissable sans perte.
  -transparente.png   Image haute definition a fond transparent : a poser sur
         un visuel dans Canva, Word, PowerPoint, Photoshop...
  -fond-blanc.png / -fond-noir.png   Image haute definition sur fond plein :
         a partager telle quelle (WhatsApp, ecran).

POUR QUE LE QR SE SCANNE TOUJOURS
  - Placez-le sur une zone UNIE : pas de photo ni de motif derriere ni autour.
  - Gardez un bon contraste : noir sur fond clair, blanc sur fond fonce.
    Ne changez pas les couleurs du QR, ne l'etirez pas, ne le retournez pas.
  - Taille minimale du QR selon la distance de lecture (regle : 1 cm de QR pour
    10 cm de distance) : chevalet a 40 cm = 4 cm minimum ; affiche a 1,5 m =
    15 cm ; ecran ou bache a 5 m = 50 cm.
  - Faites toujours un essai de scan avec un telephone avant d'imprimer en
    grand nombre.
  - Laissez visible la ligne Memora sous le QR.

Memora - Revivez votre evenement a travers les yeux de vos invites.
"""


def _readme(contacts):
    extra = "\n" + "  ·  ".join(contacts) + "\n" if contacts else ""
    return _README + extra


def build_qr_kit_zip(public_url, event_slug, site_configuration):
    matrix = qr_matrix(public_url)
    contacts = brand_contact_items(site_configuration)
    root = f"memora-qr-{event_slug}"
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{root}/LISEZ-MOI.txt", _readme(contacts).encode("utf-8"))
        for build in LAYOUTS:
            layout = build(matrix, contacts)
            mask = render_mask(layout, matrix)
            for folder, (rgb, ink_k, background, background_label) in COLORS.items():
                color_hex = "#%02x%02x%02x" % rgb
                base = f"{root}/{folder}/{layout.name}/qr-{layout.name}"
                title = f"QR code Memora - {layout.name}"
                archive.writestr(f"{base}.svg", render_svg(layout, matrix, color_hex, title).encode("utf-8"))
                archive.writestr(f"{base}.pdf", render_pdf(layout, matrix, ink_k, title))
                archive.writestr(f"{base}-transparent.png", png_from_mask(mask, rgb))
                archive.writestr(f"{base}-{background_label}.png", png_from_mask(mask, rgb, background))
    return archive_buffer.getvalue()
