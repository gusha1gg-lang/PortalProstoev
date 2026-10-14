"""Страница «Уведомления»: журнал отправок (удобно смотреть письма в разработке)."""
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.accounts.decorators import role_required
from apps.accounts.roles import ROLE_ADMIN, ROLE_DOWNTIME_SPECIALIST, ROLE_IT_MANAGER

from .models import NotificationLog


@login_required
@role_required(ROLE_IT_MANAGER, ROLE_ADMIN, ROLE_DOWNTIME_SPECIALIST)
def log_list(request):
    """Последние уведомления: что, кому и с каким итогом отправлено."""
    logs = NotificationLog.objects.select_related("rule").order_by("-created_at")[:100]
    context = {
        "logs": logs,
        "total": NotificationLog.objects.count(),
        "sent": NotificationLog.objects.filter(status=NotificationLog.Status.SENT).count(),
        "failed": NotificationLog.objects.filter(status=NotificationLog.Status.FAILED).count(),
    }
    return render(request, "notifications/log.html", context)
