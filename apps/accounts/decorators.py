"""
Проверка доступа по ролям (этап 9).

Роль в портале — это группа Django (см. roles.py). Декоратор `role_required`
пускает на страницу только пользователей с нужной ролью, остальным отдаёт 403.

Использование:
    @login_required
    @role_required(ROLE_IT_MANAGER, ROLE_ADMIN)
    def my_view(request): ...
"""
from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied


def role_required(*roles: str):
    """Пускает только пользователей с одной из указанных ролей (или суперпользователя)."""

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            user = request.user
            if not user.is_authenticated:
                # Не вошёл — отправляем на страницу входа, запомнив адрес.
                return redirect_to_login(request.get_full_path())
            if user.is_superuser or user.groups.filter(name__in=roles).exists():
                return view(request, *args, **kwargs)
            raise PermissionDenied

        return wrapper

    return decorator
