from django.urls import path

from . import views


app_name = "uploads"

urlpatterns = [
    path("souvenir/", views.guest_upload_create, name="create"),
    path("merci/", views.guest_upload_thanks, name="thanks"),
    path("diagnostic/", views.preview_diagnostic, name="preview_diagnostic"),
]
