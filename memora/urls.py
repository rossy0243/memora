from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from events.views import public_event_preview, public_movie_share
from guestbook.views import remote_capture as guestbook_remote_capture


urlpatterns = [
    path("admin/", admin.site.urls),
    path("comptes/", include("accounts.urls")),
    path("dashboard/", include("dashboard.urls")),
    path("evenements/", include("events.urls")),
    path("livre-dor/", include("guestbook.urls")),
    path("e/<slug:slug>/<slug:access_key>/film/", public_movie_share, name="public_movie"),
    # Avant le catch-all <access_key> ci-dessous : lien non secret (verrouille par un code a usage
    # unique, voir guestbook.views.remote_capture), donne aux proches qui ne peuvent pas etre presents.
    path("e/<slug:slug>/proches/", guestbook_remote_capture, name="guestbook_remote_capture"),
    path("e/<slug:slug>/<slug:access_key>/", include("uploads.urls")),
    path("e/<slug:slug>/<slug:access_key>/", public_event_preview, name="public_event"),
    path("", include("core.urls")),
]

if settings.DEBUG and settings.MEMORA_STORAGE_BACKEND == "local":
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
