"""
Базовые настройки — общие для всех окружений.

Сам этот файл напрямую не запускается: его импортируют dev.py (разработка)
и prod.py (прод). Разница между средами — только в значениях.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# Корень проекта — папка, где лежит manage.py.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Подхватываем переменные из файла .env (если он есть рядом с manage.py).
load_dotenv(BASE_DIR / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    """Читает переменную окружения как флаг True/False."""
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    """Читает переменную окружения как список через запятую."""
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


# --- Безопасность ---
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-insecure-key-change-me")
DEBUG = env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")

# --- Приложения ---
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Наши приложения (apps/...)
    "apps.accounts",
    "apps.catalog",
    "apps.downtimes",
    "apps.sla",
    "apps.integrations",
    "apps.reports",
    "apps.notifications",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# --- База данных приложения (PostgreSQL) ---
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("POSTGRES_DB", "portalprostoev"),
        "USER": os.getenv("POSTGRES_USER", "portal"),
        "PASSWORD": os.getenv("POSTGRES_PASSWORD", "portal"),
        "HOST": os.getenv("POSTGRES_HOST", "localhost"),
        "PORT": os.getenv("POSTGRES_PORT", "5432"),
        "OPTIONS": {"connect_timeout": 5},
    }
}

# --- Проверка паролей ---
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- Локализация ---
LANGUAGE_CODE = "ru-ru"
TIME_ZONE = "Europe/Moscow"
USE_I18N = True
USE_TZ = True

# --- Статические файлы ---
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
# Наши общие статические файлы (стили, библиотека графиков) лежат в папке static/.
STATICFILES_DIRS = [BASE_DIR / "static"]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Флаги интеграций (читаются адаптерами на этапе 6) ---
INTEGRATION_MODE = os.getenv("INTEGRATION_MODE", "mock")  # mock | live
AUTH_MODE = os.getenv("AUTH_MODE", "dev")                 # dev  | adfs

# --- Oracle (источник простоев) — только для INTEGRATION_MODE=live ---
ORACLE_USER = os.getenv("ORACLE_USER", "")
ORACLE_PASSWORD = os.getenv("ORACLE_PASSWORD", "")
ORACLE_DSN = os.getenv("ORACLE_DSN", "")
# Таблица/представление с простоями. Уточняется после выдачи доступа (question.md, В17).
ORACLE_DOWNTIME_TABLE = os.getenv("ORACLE_DOWNTIME_TABLE", "DOWNTIMES")

# --- OMNITRACKER (ITIL-тикеты) — только для INTEGRATION_MODE=live ---
OMNITRACKER_BASE_URL = os.getenv("OMNITRACKER_BASE_URL", "")
OMNITRACKER_USER = os.getenv("OMNITRACKER_USER", "")
OMNITRACKER_PASSWORD = os.getenv("OMNITRACKER_PASSWORD", "")

# --- Почта (уведомления, этап 8) ---
# В разработке письма печатаются в консоль. На проде backend = SMTP (см. prod.py),
# реквизиты — из .env (уточняются у коллег из ПИ-ПС, question.md, В22).
EMAIL_BACKEND = os.getenv("DJANGO_EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = os.getenv("EMAIL_HOST", "")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "25"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", False)
EMAIL_USE_SSL = env_bool("EMAIL_USE_SSL", False)
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "portal@localhost")
# Порог предупреждения SLA по умолчанию (используется, если у правила не задан свой).
NOTIFICATION_SLA_WARNING_PERCENT = int(os.getenv("NOTIFICATION_SLA_WARNING_PERCENT", "80"))
