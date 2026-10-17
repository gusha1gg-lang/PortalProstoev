"""Кто может вести разборы (создавать, быть ведущим, согласовывать).

Роли уточняются позже; сейчас — как у синхронизации и справочников:
руководитель ИТ, специалист по простоям и администратор.
"""
from apps.accounts.roles import ROLE_ADMIN, ROLE_DOWNTIME_SPECIALIST, ROLE_IT_MANAGER

REVIEW_ROLES = (ROLE_DOWNTIME_SPECIALIST, ROLE_IT_MANAGER, ROLE_ADMIN)


def can_manage_reviews(user) -> bool:
    """Может ли пользователь вести разбор (создавать, быть ведущим, согласовывать)."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name__in=REVIEW_ROLES).exists()


def can_edit_review(user, review) -> bool:
    """Может ли пользователь править конкретный разбор.

    Пока — роли из `REVIEW_ROLES` и сам ведущий. Участники (приглашённые) получат
    доступ на шаге «чат и участники».
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or can_manage_reviews(user):
        return True
    return user.pk == review.lead_id
