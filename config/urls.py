"""Корневая маршрутизация URL проекта."""
from django.conf import settings
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),                     # стандартная админка Django
    path("accounts/", include("apps.accounts.urls")),    # вход/выход
    path("sla/", include("apps.sla.urls")),              # расчёт потерь и SLA
    path("notifications/", include("apps.notifications.urls")),  # журнал уведомлений
    path("sync/", include("apps.integrations.urls")),    # синхронизация простоев (этап 11.6)
    path("", include("apps.reports.urls")),              # дашборд (главная), SLA-отчёт, выгрузка
]

# Маршруты корпоративного входа (SSO). Нужны на проде (AUTH_MODE=adfs): по ним портал
# возвращает сотрудника после входа. Подключаем ТОЛЬКО когда SSO включён — иначе на
# разработке, где пакет django-auth-adfs не установлен, портал не запустился бы.
if getattr(settings, "AUTH_MODE", "dev") == "adfs":
    urlpatterns.append(path("oauth2/", include("django_auth_adfs.urls")))
