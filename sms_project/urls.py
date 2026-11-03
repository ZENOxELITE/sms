from django.urls import path

from portal import views


urlpatterns = [
    path("", views.login, name="login"),
    path("login", views.login_submit, name="login_submit"),
    path("password-reset", views.password_reset, name="password_reset"),
    path("logout", views.logout, name="logout"),
    path("dashboard", views.dashboard, name="dashboard"),
    path("portal/<str:role>", views.portal_home, name="portal_home"),
    path("portal/<str:role>/<str:section>", views.portal_page, name="portal_page"),
    path("map", views.map_page, name="map_page"),
    path("health/supabase", views.supabase_health, name="supabase_health"),
]
