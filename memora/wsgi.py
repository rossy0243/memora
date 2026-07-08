"""WSGI config for Memora."""
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "memora.settings")

application = get_wsgi_application()
