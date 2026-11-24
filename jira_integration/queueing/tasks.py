from functools import cache

from django.conf import settings
from procrastinate.contrib.django import app
from procrastinate.exceptions import AlreadyEnqueued

from jira_integration.sources import get_source
from jira_integration.sources.rest_source import RestSource
from jira_integration.sync.paged import process_step

from .models import SyncCursor


@cache
def worker_source():
    # Одна HTTP-сессия и кэш справочников на процесс воркера.
    source = get_source()
    if isinstance(source, RestSource):
        source.http.defer_rate_limits = True
    return source


@app.periodic(cron="* * * * *")
@app.task(queue="jira", queueing_lock="jira-read-step")
def sync_page(timestamp=None):
    """Периодический сигнал восстанавливает цепочку после падения воркера."""
    source = worker_source()
    more = process_step(
        source,
        poll_seconds=settings.JIRA_SYNC_INTERVAL_SEC,
        reconcile_seconds=settings.JIRA_RECONCILE_INTERVAL_SEC,
    )
    next_due = None
    if not more:
        next_due = SyncCursor.objects.values_list("next_due", flat=True).get(
            pk=source.kind
        )

    try:
        sync_page.configure(schedule_at=next_due).defer()
    except AlreadyEnqueued:
        # Таймер успел поставить следующий шаг, пока текущий обрабатывал страницу.
        pass
