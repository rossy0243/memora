"""Analyse heuristique d'une piece d'identite scannee, a la soumission d'une
candidature Ambassadeur.

IMPORTANT — ce que ceci n'est PAS : une detection de faux documents fiable a
100%. Aucune analyse purement logicielle (sans base de donnees officielle ni
service de verification specialise) ne peut le garantir. C'est un outil de
PRIORISATION pour la revue humaine : il repere des indices statistiquement
correles a une retouche (logiciel d'edition dans les metadonnees, zone
recompressee differemment du reste de l'image) et les signale a l'administrateur
Memora, qui reste seul decisionnaire (voir AmbassadorApplication.approve/reject).

Deux techniques, toutes deux realisables avec Pillow seul (deja une dependance,
pas de nouvelle lib a installer) :
  1. Metadonnees EXIF : absence totale (souvent le signe d'un re-enregistrement
     ou d'un export d'un logiciel de retouche) ou tag "Software" connu.
  2. Error Level Analysis (ELA) : recompresser l'image et comparer au fichier
     d'origine. Une zone retouchee-puis-re-enregistree localement recompresse
     differemment du reste de la photo, ce qui cree un pic d'erreur localise.
"""
import io
import logging

from PIL import Image, ImageChops, ImageStat

logger = logging.getLogger(__name__)

# Logiciels de retouche courants (mobile et desktop) susceptibles d'apparaitre
# dans le tag EXIF "Software" d'une image qui a ete editee puis re-exportee.
_EDITING_SOFTWARE_HINTS = (
    "photoshop",
    "gimp",
    "pixlr",
    "snapseed",
    "lightroom",
    "affinity photo",
    "canva",
    "picsart",
    "facetune",
)

# Tag EXIF standard (baseline TIFF) pour le logiciel ayant produit/modifie le fichier.
_EXIF_SOFTWARE_TAG = 305


def _exif_flags(image):
    flags = []
    score = 0
    try:
        exif = image.getexif()
    except Exception:
        exif = None

    if not exif:
        flags.append(
            "Aucune métadonnée EXIF (fichier réenregistré, capture d'écran, "
            "ou export depuis un logiciel de retouche)."
        )
        score += 15
        return flags, score

    software = exif.get(_EXIF_SOFTWARE_TAG)
    if software and any(hint in str(software).lower() for hint in _EDITING_SOFTWARE_HINTS):
        flags.append(f"Logiciel de retouche détecté dans les métadonnées ({software}).")
        score += 40

    return flags, score


def _resolution_flags(image):
    flags = []
    score = 0
    longest_side = max(image.size)
    if longest_side < 800:
        flags.append(
            f"Résolution faible ({image.size[0]}×{image.size[1]}px) : document "
            "difficile à vérifier visuellement."
        )
        score += 10
    return flags, score


def _error_level_analysis(image, quality=90, grid=16):
    """Renvoie (erreur_max, erreur_mediane) d'une carte d'erreur de
    recompression JPEG, decoupee en blocs. Un bloc dont l'erreur s'ecarte
    fortement de la mediane trahit souvent une zone retouchee puis
    re-enregistree independamment du reste de l'image."""
    rgb = image.convert("RGB")
    buffer = io.BytesIO()
    rgb.save(buffer, format="JPEG", quality=quality)
    buffer.seek(0)
    resaved = Image.open(buffer)
    diff = ImageChops.difference(rgb, resaved)

    width, height = diff.size
    step_x = max(width // grid, 1)
    step_y = max(height // grid, 1)

    block_errors = []
    for top in range(0, height, step_y):
        for left in range(0, width, step_x):
            box = (left, top, min(left + step_x, width), min(top + step_y, height))
            stat = ImageStat.Stat(diff.crop(box))
            block_errors.append(sum(stat.stddev) / len(stat.stddev))

    if not block_errors:
        return 0.0, 0.0
    block_errors.sort()
    median_error = block_errors[len(block_errors) // 2]
    return max(block_errors), median_error


def _ela_flags(image):
    flags = []
    score = 0
    try:
        max_error, median_error = _error_level_analysis(image)
    except Exception:
        logger.warning("Error level analysis failed", exc_info=True)
        return flags, score

    if max_error > 8 and median_error > 0 and (max_error / median_error) > 3.0:
        flags.append(
            "Zone de compression anormale détectée (analyse ELA) : "
            "possible retouche localisée."
        )
        score += 35
    return flags, score


def analyze_identity_document(file_obj):
    """Analyse `file_obj` (fichier uploade, deja valide comme image JPEG/PNG) et
    renvoie {"risk_score": 0-100, "flags": [...]}. Ne leve pas d'exception sur un
    fichier illisible : renvoie un score neutre et journalise (l'admin verra un
    dossier sans indice automatique, pas un plantage de la candidature)."""
    try:
        file_obj.seek(0)
        image = Image.open(file_obj)
        image.load()
    except Exception:
        logger.warning("Identity document analysis could not open the file", exc_info=True)
        return {"risk_score": 0, "flags": []}
    finally:
        try:
            file_obj.seek(0)
        except Exception:
            pass

    flags = []
    score = 0
    for check in (_exif_flags, _resolution_flags, _ela_flags):
        check_flags, check_score = check(image)
        flags.extend(check_flags)
        score += check_score

    return {"risk_score": min(score, 100), "flags": flags}


def risk_level_label(score):
    if score >= 50:
        return "Élevé"
    if score >= 20:
        return "Moyen"
    return "Faible"
