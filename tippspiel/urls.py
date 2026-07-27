from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.shortcuts import redirect
from django.urls import include, path


def root_redirect(request):
    if request.user.is_authenticated:
        return redirect("dashboard")

    return redirect("account_login")


urlpatterns = [
    path("admin/", admin.site.urls),

    # Login, Registrierung, Logout und Passwortverwaltung
    path("accounts/", include("allauth.urls")),

    # Startseite
    path("", root_redirect, name="root"),

    # Tippspiel
    path("", include("tipping.urls")),
]


# Hochgeladene Dateien nur lokal über Django ausliefern.
if settings.DEBUG:
    urlpatterns += static(
        settings.MEDIA_URL,
        document_root=settings.MEDIA_ROOT,
    )