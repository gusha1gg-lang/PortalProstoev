"""Кто и что может в разборах (роли, участники, ведущий).

Роли уточняются позже; сейчас «вести» могут руководитель ИТ, специалист по простоям
и администратор (см. `REVIEW_ROLES`). Кроме них к разбору допускаются **участники**
(приглашённые, в том числе «Оператор») — но видят они только свои разборы.
"""
from django.db.models import Q

from apps.accounts.roles import ROLE_ADMIN, ROLE_DOWNTIME_SPECIALIST, ROLE_IT_MANAGER

from .models import IncidentReview

REVIEW_ROLES = (ROLE_DOWNTIME_SPECIALIST, ROLE_IT_MANAGER, ROLE_ADMIN)


def can_manage_reviews(user) -> bool:
    """Может ли пользователь вообще вести разборы (создавать, быть ведущим, согласовывать)."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name__in=REVIEW_ROLES).exists()


def is_participant(user, review) -> bool:
    """Является ли пользователь участником разбора."""
    if not user or not user.is_authenticated or review is None:
        return False
    return review.participants.filter(user=user).exists()


def can_view_review(user, review) -> bool:
    """Может ли пользователь открыть разбор: роли, ведущий, автор или участник."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or can_manage_reviews(user):
        return True
    if review is None:
        return False
    if review.lead_id == user.pk or review.created_by_id == user.pk:
        return True
    return is_participant(user, review)


def can_edit_review(user, review) -> bool:
    """Может ли пользователь дополнять разбор: хронология и чат (роли, ведущий, участник)."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or can_manage_reviews(user):
        return True
    if review is None:
        return False
    if review.lead_id == user.pk:
        return True
    return is_participant(user, review)


def can_manage_review(user, review) -> bool:
    """Может ли пользователь управлять разбором: статус, участники, согласование."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or can_manage_reviews(user):
        return True
    return review is not None and review.lead_id == user.pk


def visible_reviews(user):
    """Разборы, которые пользователь вправе видеть.

    Роли/администратор видят все; остальные — только те, где они ведущий, автор или участник.
    """
    queryset = IncidentReview.objects.all()
    if user.is_superuser or can_manage_reviews(user):
        return queryset
    return queryset.filter(
        Q(lead=user) | Q(created_by=user) | Q(participants__user=user)
    ).distinct()
