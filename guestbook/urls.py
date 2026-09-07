from django.urls import path

from . import views


app_name = "guestbook"

urlpatterns = [
    path("mission/", views.agent_home, name="agent_home"),
    path("mission/<int:pk>/", views.guestbook_capture, name="capture"),
    path("mission/<int:pk>/terminer/", views.end_shift, name="end_shift"),
]
