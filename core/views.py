from urllib.parse import urljoin

from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone


def absolute_public_url(request, path):
    base_url = settings.MEMORA_PUBLIC_BASE_URL.rstrip("/")
    if not base_url:
        base_url = f"{request.scheme}://{request.get_host()}"
    return urljoin(f"{base_url}/", path.lstrip("/"))


def home(request):
    if request.user.is_authenticated:
        return redirect("dashboard:home")
    return render(request, "core/home.html")


def ambassador_program(request):
    return render(request, "core/ambassador_program.html")


def health(request):
    return HttpResponse("ok", content_type="text/plain")


def robots_txt(request):
    sitemap_url = absolute_public_url(request, reverse("core:sitemap"))
    content = "\n".join(
        [
            "User-agent: *",
            "Allow: /",
            "Disallow: /admin/",
            "Disallow: /dashboard/",
            "Disallow: /comptes/",
            "Disallow: /evenements/",
            f"Sitemap: {sitemap_url}",
            "",
        ]
    )
    return HttpResponse(content, content_type="text/plain")


def sitemap_xml(request):
    home_url = absolute_public_url(request, reverse("core:home"))
    program_url = absolute_public_url(request, reverse("core:ambassador_program"))
    lastmod = timezone.now().date().isoformat()
    content = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>{home_url}</loc>
    <lastmod>{lastmod}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>1.0</priority>
  </url>
  <url>
    <loc>{program_url}</loc>
    <lastmod>{lastmod}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.7</priority>
  </url>
</urlset>
"""
    return HttpResponse(content, content_type="application/xml")
