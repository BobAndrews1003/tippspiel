from django.contrib import admin
from django.shortcuts import redirect
from django.urls import include, path


def root_redirect(request):
    if request.user.is_authenticated:
        return redirect("tippen")

    return redirect("account_login")


urlpatterns = [
    path("admin/", admin.site.urls),

    # Login, Registrierung, Logout, Passwortverwaltung und Social Login
    path("accounts/", include("allauth.urls")),

    # Startseite und Tippspiel
    path("", root_redirect, name="root"),
    path("", include("tipping.urls")),
]