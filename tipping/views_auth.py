from django.contrib.auth import login
from django.shortcuts import render, redirect

from .forms import SignupForm


def signup(request):
    if request.method == "POST":
        form = SignupForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect("join_group")  # nach Registrierung direkt Gruppe beitreten
    else:
        form = SignupForm()

    return render(request, "registration/signup.html", {"form": form})
