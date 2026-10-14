"""
Настройки ADFS (корпоративный вход) — подключаются только при AUTH_MODE=adfs.

Смысл: весь код входа держим в одном месте, а в prod.py просто вызываем apply_adfs().
В разработке этот модуль не используется вообще, поэтому пакет django-auth-adfs
на dev не нужен и не устанавливается (см. requirements-live.txt).
"""
import os


def apply_adfs(namespace: dict) -> None:
    """
    Включает ADFS в переданных настройках (namespace — это globals() модуля настроек).

    Добавляет приложение, middleware и бэкенд аутентификации, а параметры подключения
    берёт из переменных окружения (.env). Секреты в репозиторий не попадают.
    """
    namespace["INSTALLED_APPS"] = list(namespace["INSTALLED_APPS"]) + ["django_auth_adfs"]

    # Middleware пакета требует вход для всех страниц (кроме служебных) — то, что нужно на проде.
    namespace["MIDDLEWARE"] = list(namespace["MIDDLEWARE"]) + [
        "django_auth_adfs.middleware.LoginRequiredMiddleware",
    ]

    # Сначала пробуем вход через ADFS, затем — обычный (служебные учётки).
    namespace["AUTHENTICATION_BACKENDS"] = [
        "django_auth_adfs.backend.AdfsAuthCodeBackend",
        "django.contrib.auth.backends.ModelBackend",
    ]

    namespace["AUTH_ADFS"] = {
        "SERVER": os.getenv("ADFS_SERVER", ""),
        "CLIENT_ID": os.getenv("ADFS_CLIENT_ID", ""),
        "CLIENT_SECRET": os.getenv("ADFS_CLIENT_SECRET", ""),
        "TENANT_ID": os.getenv("ADFS_TENANT_ID", ""),
        # Relying Party в ADFS (кто мы для сервера входа).
        "RELYING_PARTY_ID": os.getenv("ADFS_RELYING_PARTY_ID", ""),
        # Какие поля брать из «удостоверения» пользователя.
        "USERNAME_CLAIM": os.getenv("ADFS_USERNAME_CLAIM", "winaccountname"),
        "GROUPS_CLAIM": os.getenv("ADFS_GROUPS_CLAIM", "group"),
        "CLAIM_MAPPING": {
            "first_name": "given_name",
            "last_name": "family_name",
            "email": "email",
        },
        # Группы AD попадают в Django-группы; дальше мы сопоставляем их с ролями портала
        # (apps/accounts/roles.py, AD_GROUP_TO_ROLE).
        "MIRROR_GROUPS": True,
    }
