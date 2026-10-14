"""
Маршруты входа/выхода.

В разработке используется обычная страница входа Django (логин/пароль).
На проде ADFS перехватывает вход через middleware, и эти страницы нужны
только для служебных учёток (AUTH_MODE=dev).
"""
from django.contrib.auth import views as auth_views
from django.urls import path

app_name = "accounts"

urlpatterns = [
    path(
        "login/",
        auth_views.LoginView.as_view(template_name="accounts/login.html", redirect_authenticated_user=True),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
]
