from django.urls import path

from . import views


app_name = "events"

urlpatterns = [
    path("nouveau/", views.EventCreateView.as_view(), name="create"),
    path("<int:pk>/", views.EventDetailView.as_view(), name="detail"),
    path("<int:pk>/medias/", views.EventMediaListView.as_view(), name="media_list"),
    path("<int:pk>/medias/<int:upload_pk>/selection-film/", views.toggle_movie_selection, name="toggle_movie_selection"),
    path("<int:pk>/medias/<int:upload_pk>/moderation/", views.set_media_moderation_status, name="set_media_moderation"),
    path("<int:pk>/modifier/", views.EventUpdateView.as_view(), name="update"),
    path("<int:pk>/generer-film/", views.generate_movie, name="generate_movie"),
    path("<int:pk>/telecharger-zip/", views.download_event_zip, name="download_zip"),
    path("public/<slug:slug>/<slug:access_key>/", views.public_event_preview, name="public-preview"),
]
