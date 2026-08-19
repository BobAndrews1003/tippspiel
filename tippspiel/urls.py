from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from allauth.account.decorators import secure_admin_login
from django.shortcuts import redirect
from django.urls import include, path

from tipping.health import health_check


# Der Django-Admin verwendet standardmäßig nicht den
# Allauth-Login. Dadurch würden Allauth-Rate-Limits und
# weitere Login-Schutzmechanismen dort nicht greifen.
admin.autodiscover()
admin.site.login = secure_admin_login(
    admin.site.login
)


def root_redirect(request):
    if request.user.is_authenticated:
        return redirect("dashboard")

    return redirect("account_login")


urlpatterns = [
    path(
        "health/",
        health_check,
        name="health_check",
    ),

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
