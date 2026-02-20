from django.urls import path
from django.contrib.auth import views as auth_views

from . import views
from . import views_auth
from .forms import EmailOrUsernameAuthenticationForm

urlpatterns = [
    # App-Seiten
    path("tippen/", views.tippen, name="tippen"),
    path("bonus/", views.bonus_tips, name="bonus_tips"),
    path("spieltag/", views.spieltag, name="spieltag"),
    path("tabelle/", views.tabelle, name="tabelle"),
    path("join/", views.join_group, name="join_group"),
    path("create-group/", views.create_group, name="create_group"),
    path("set-active-group/", views.set_active_group, name="set_active_group"),



    # ✅ NEU: User-Statistik
    path("stats/<int:user_id>/", views.user_stats, name="user_stats"),

    # Auth
    path(
        "accounts/login/",
        auth_views.LoginView.as_view(
            template_name="registration/login.html",
            authentication_form=EmailOrUsernameAuthenticationForm,
        ),
        name="login",
    ),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("accounts/signup/", views_auth.signup, name="signup"),
]
