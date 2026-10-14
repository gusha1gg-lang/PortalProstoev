"""Страница «Уведомления»: журнал отправок (удобно смотреть письма в разработке)."""
from django.shortcuts import render

from .models import NotificationLog


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
