from django.urls import path

from . import views


app_name = "events"

urlpatterns = [
    path("nouveau/", views.EventCreateView.as_view(), name="create"),
    path("<int:pk>/", views.EventDetailView.as_view(), name="detail"),
    path("<int:pk>/modifier/", views.EventUpdateView.as_view(), name="update"),
    path("<int:pk>/telecharger-zip/", views.download_event_zip, name="download_zip"),
    path("public/<slug:slug>/", views.public_event_preview, name="public-preview"),
]
