from django.contrib.auth import views as auth_views
from django.urls import path

from . import views


app_name = "accounts"

urlpatterns = [
    path("inscription/", views.signup, name="signup"),
    path(
        "connexion/",
        views.RoleAwareLoginView.as_view(),
        name="login",
    ),
    path(
        "deconnexion/",
        auth_views.LogoutView.as_view(),
        name="logout",
    ),
    path("mot-de-passe-oublie/", views.password_help, name="password_help"),
    path(
        "mot-de-passe/reinitialiser/",
        views.OrganizerPasswordResetView.as_view(),
        name="password_reset",
    ),
    path(
        "mot-de-passe/reinitialiser/envoye/",
        views.OrganizerPasswordResetDoneView.as_view(),
        name="password_reset_done",
    ),
    path(
        "mot-de-passe/reinitialiser/<uidb64>/<token>/",
        views.OrganizerPasswordResetConfirmView.as_view(),
        name="password_reset_confirm",
    ),
    path(
        "mot-de-passe/reinitialiser/termine/",
        views.OrganizerPasswordResetCompleteView.as_view(),
        name="password_reset_complete",
    ),
    path("gains/retrait/", views.request_payout_view, name="request_payout"),
    path("mes-donnees/", views.export_my_data, name="export_data"),
    path("devenir-ambassadeur/", views.become_ambassador, name="become_ambassador"),
]
