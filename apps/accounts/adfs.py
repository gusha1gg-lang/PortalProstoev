"""
Подключение корпоративного входа ADFS (только при AUTH_MODE=adfs).

Здесь две вещи:
    1) назначение ролей портала по группам AD при входе сотрудника;
    2) подключение «сигнала» входа из пакета django-auth-adfs.

Пакет django-auth-adfs на разработке не установлен, поэтому импортируется
внутри функций и только когда AUTH_MODE=adfs. Так dev-среда остаётся простой.
"""
from django.contrib.auth.models import Group
from django.conf import settings


def apply_ad_roles(user, ad_groups) -> list[str]:
    """
    Назначает роли портала пользователю по группам AD.

    Роли портала — это обычные группы Django. Пользователь, вошедший из AD,
    получает набор ролей, которые мы сопоставили по карте AD_GROUP_TO_ROLE.
    Возвращает список выданных ролей (для журнала/тестов).
    """
    from .roles import roles_for_ad_groups

    role_names = roles_for_ad_groups(ad_groups)
    user.groups.set(Group.objects.filter(name__in=role_names))
    return role_names


def connect_signals() -> None:
    """
    Подключает обработчик успешного входа из django-auth-adfs.

    Если пакета нет (например, случайно включили AUTH_MODE=adfs на dev) —
    тихо выходим, чтобы портал не падал при старте.
    """
    try:
        from django_auth_adfs.signals import post_authenticate
    except Exception:  # noqa: BLE001 — пакет нужен только на проде
        return

    post_authenticate.connect(_on_adfs_login, dispatch_uid="accounts.adfs_roles")


def _on_adfs_login(sender, user, claims, **kwargs) -> None:  # noqa: ARG001
    """Обработчик входа: берём группы из «удостоверения» и назначаем роли."""
    claim_name = settings.AUTH_ADFS.get("GROUPS_CLAIM", "group")
    groups = claims.get(claim_name, []) or []
    apply_ad_roles(user, groups)
