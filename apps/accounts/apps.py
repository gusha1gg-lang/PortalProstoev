from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts"
    verbose_name = "Пользователи и роли"

    def ready(self):
        """На проде подключаем назначение ролей по группам AD (см. adfs.py)."""
        from django.conf import settings

        if getattr(settings, "AUTH_MODE", "dev") == "adfs":
            from . import adfs

            adfs.connect_signals()
