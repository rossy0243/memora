"""Genere les visuels de marque pour les reseaux sociaux (SVG maitres + PNG haute definition).

    python manage.py build_brand_assets --chrome "C:/Program Files/Google/Chrome/Application/chrome.exe"

Sans --chrome, seuls les SVG sont ecrits. Les PNG sont rasterises a la taille exacte du SVG
par Chrome sans affichage (rendu vectoriel net, sans police a installer : le texte est en courbes).
"""
import subprocess
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from events.brand_assets import ASSETS


class Command(BaseCommand):
    help = "Ecrit les visuels de marque (icone, logo + nom, banniere) dans assets/brand/."

    def add_arguments(self, parser):
        parser.add_argument("--chrome", default="", help="Chemin de Chrome/Chromium, pour produire les PNG.")
        parser.add_argument("--output", default="", help="Dossier de sortie (defaut : assets/brand).")

    def handle(self, *args, **options):
        output = Path(options["output"] or Path(settings.BASE_DIR) / "assets" / "brand")
        output.mkdir(parents=True, exist_ok=True)
        chrome = options["chrome"]
        if chrome and not Path(chrome).exists():
            raise CommandError(f"Chrome introuvable : {chrome}")

        for name, (build, width, height) in ASSETS.items():
            svg_path = output / f"{name}.svg"
            svg_path.write_text(build(), encoding="utf-8")
            self.stdout.write(f"{svg_path}")
            if not chrome:
                continue
            png_path = output / f"{name}.png"
            with tempfile.TemporaryDirectory() as tmp:
                page = Path(tmp) / "page.html"
                page.write_text(
                    f'<!doctype html><body style="margin:0;background:transparent">'
                    f'<img src="{svg_path.resolve().as_uri()}" width="{width}" height="{height}" style="display:block">',
                    encoding="utf-8",
                )
                subprocess.run(
                    [
                        chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                        "--force-device-scale-factor=1", f"--window-size={width},{height}",
                        f"--screenshot={png_path}", page.as_uri(),
                    ],
                    check=True, capture_output=True, timeout=120,
                )
            self.stdout.write(f"{png_path}")
