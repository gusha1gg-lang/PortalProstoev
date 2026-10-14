"""
Настройки для прода (Oracle Linux в корпоративной доменной сети).
Запуск:  DJANGO_SETTINGS_MODULE=config.settings.prod gunicorn config.wsgi
"""
from .base import *  # noqa: F401,F403
from .base import env_bool, env_list

import os

DEBUG = False

# Доменные имена сервера задаются в .env на проде.
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "")

# Доверенные источники для CSRF (например, https://portal.company.local).
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS", "")

# --- Базовые требования безопасности для прода ---
SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", True)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

# --- Аутентификация (этап 9) ---
# На проде по умолчанию корпоративный вход ADFS. Флагом AUTH_MODE можно временно
# вернуть обычный вход (например, чтобы зайти служебной учёткой для настройки).
AUTH_MODE = os.getenv("AUTH_MODE", "adfs")
if AUTH_MODE == "adfs":
    from .adfs import apply_adfs

    apply_adfs(globals())

# На проде письма уходят через реальный почтовый сервер (реквизиты — в .env).
EMAIL_BACKEND = os.getenv("DJANGO_EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend")
