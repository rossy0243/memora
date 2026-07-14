from urllib.parse import urljoin

from django.conf import settings
from django.templatetags.static import static


def site_metadata(request):
    site_url = settings.MEMORA_PUBLIC_BASE_URL.rstrip("/")
    if not site_url and request:
        site_url = f"{request.scheme}://{request.get_host()}"

    path = request.path if request else "/"
    canonical_url = urljoin(f"{site_url}/", path.lstrip("/")) if site_url else path
    default_og_image = urljoin(f"{site_url}/", static("img/memora-hero.png").lstrip("/")) if site_url else static("img/memora-hero.png")

    return {
        "site_name": "Memora",
        "site_url": site_url,
        "canonical_url": canonical_url,
        "default_og_image": default_og_image,
    }
