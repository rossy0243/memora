from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from events.views import public_event_preview


urlpatterns = [
    path("admin/", admin.site.urls),
    path("comptes/", include("accounts.urls")),
    path("dashboard/", include("dashboard.urls")),
    path("evenements/", include("events.urls")),
    path("e/<slug:slug>/", include("uploads.urls")),
    path("e/<slug:slug>/", public_event_preview, name="public_event"),
    path("", include("core.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
