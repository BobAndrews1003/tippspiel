from django.contrib import admin
from django.urls import path, include
from django.shortcuts import redirect

def root_redirect(request):
    return redirect("/accounts/login/")  # 🔥 hier zur Login-Seite

urlpatterns = [
    path("", root_redirect, name="root"),   # ✅ Root abfangen
    path("", include("tipping.urls")),      # deine App-Routen
    path("admin/", admin.site.urls),
]