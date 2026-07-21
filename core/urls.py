from django.urls import path

from . import views


app_name = "core"

urlpatterns = [
    path("", views.home, name="home"),
    path("programme-ambassadeur/", views.ambassador_program, name="ambassador_program"),
    path("cgu/", views.terms_of_service, name="terms"),
    path("confidentialite/", views.privacy_policy, name="privacy"),
    path("health/", views.health, name="health"),
    path("robots.txt", views.robots_txt, name="robots"),
    path("sitemap.xml", views.sitemap_xml, name="sitemap"),
]
