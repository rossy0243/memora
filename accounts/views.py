from django.contrib.auth import login
from django.shortcuts import redirect, render

from .forms import OrganizerSignupForm


def signup(request):
    if request.user.is_authenticated:
        return redirect("dashboard:home")

    if request.method == "POST":
        form = OrganizerSignupForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect("dashboard:home")
    else:
        form = OrganizerSignupForm()

    return render(request, "accounts/signup.html", {"form": form})
