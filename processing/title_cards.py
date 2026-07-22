"""Cartons typographiques du film souvenir (ouverture et generique de fin).

Generes avec Pillow, deja present dans les dependances : pas de service Node ni de
navigateur headless a faire tourner sur le worker.
"""
import logging
from pathlib import Path

from django.conf import settings
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

# Polices essayees dans l'ordre. La premiere trouvee gagne.
# fonts-dejavu-core est installe par le Dockerfile ; les chemins Windows servent au dev.
FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    r"C:\Windows\Fonts\georgiab.ttf",
    r"C:\Windows\Fonts\georgia.ttf",
    r"C:\Windows\Fonts\arialbd.ttf",
    r"C:\Windows\Fonts\arial.ttf",
)

BACKGROUND_COLOR = (36, 31, 34)      # --color-ink de la charte
TITLE_COLOR = (255, 255, 255)
SUBTITLE_COLOR = (216, 180, 106)     # champagne


def _font_search_paths():
    """Chemins de police, du plus specifique au plus generique."""
    configured = getattr(settings, "MEMORA_MOVIE_TITLE_FONT_PATH", "")
    if configured:
        yield configured

    # Une police deposee dans assets/fonts/ prime sur celles du systeme.
    bundled = Path(settings.BASE_DIR) / "assets" / "fonts"
    if bundled.exists():
        for path in sorted(bundled.glob("*.ttf")):
            yield str(path)

    yield from FONT_CANDIDATES


def resolve_title_font(size):
    """Charge une police vectorielle, sinon retombe sur celle de Pillow.

    Le repli evite de faire echouer un film pour une police manquante, mais le
    rendu est nettement moins soigne : mieux vaut fournir un vrai fichier TTF.
    """
    for candidate in _font_search_paths():
        try:
            return ImageFont.truetype(candidate, size)
        except Exception:
            continue

    logger.warning("Aucune police vectorielle trouvee : rendu des cartons degrade.")
    return ImageFont.load_default()


def _draw_centered(draw, text, font, color, center_x, baseline_y):
    if not text:
        return baseline_y
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    draw.text(
        (center_x - (right - left) / 2, baseline_y - (bottom - top) / 2),
        text,
        font=font,
        fill=color,
    )
    return baseline_y + (bottom - top)


def build_title_card(output_path, width, height, title, subtitle=""):
    """Dessine un carton sobre : titre centre, sous-titre en capitales espacees."""
    image = Image.new("RGB", (width, height), BACKGROUND_COLOR)
    draw = ImageDraw.Draw(image)

    title_font = resolve_title_font(max(int(height * 0.085), 12))
    subtitle_font = resolve_title_font(max(int(height * 0.028), 10))

    center_x = width / 2
    _draw_centered(draw, title, title_font, TITLE_COLOR, center_x, height * 0.46)
    if subtitle:
        spaced = " ".join(subtitle.upper())
        _draw_centered(draw, spaced, subtitle_font, SUBTITLE_COLOR, center_x, height * 0.58)

    # Filet fin sous le titre : detail discret qui structure le carton.
    rule_width = width * 0.12
    rule_y = height * 0.53
    draw.line(
        [(center_x - rule_width / 2, rule_y), (center_x + rule_width / 2, rule_y)],
        fill=SUBTITLE_COLOR,
        width=max(int(height * 0.002), 1),
    )

    output_path = Path(output_path)
    image.save(output_path, format="PNG")
    return output_path


def event_intro_texts(event):
    """Titre et sous-titre du carton d'ouverture."""
    title = (getattr(event, "couple_name", "") or getattr(event, "title", "") or "").strip()
    event_date = getattr(event, "event_date", None)
    subtitle = event_date.strftime("%d/%m/%Y") if event_date else ""
    return title, subtitle


def event_outro_texts(event):
    """Titre et sous-titre du carton de fin.

    Un film qui s'arrete net sur le dernier plan donne une impression d'inacheve :
    le carton de fin referme le recit et remercie ceux qui l'ont nourri.
    """
    name = (getattr(event, "couple_name", "") or getattr(event, "title", "") or "").strip()
    title = settings.MEMORA_MOVIE_OUTRO_TITLE or "Merci"
    subtitle = name or "Memora"
    return title, subtitle
