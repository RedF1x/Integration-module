from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.db import connection
from django.utils import timezone
from procrastinate.exceptions import AlreadyEnqueued

from jira_integration.queueing import tasks
from jira_integration.queueing.models import SyncCursor


@pytest.mark.django_db
@pytest.mark.parametrize("more", [True, False])
def test_next_job_is_immediate_for_page_or_scheduled_for_poll(monkeypatch, more):
    next_due = timezone.now() + timedelta(minutes=10)
    SyncCursor.objects.create(pk="mock", next_due=next_due)
    source = SimpleNamespace(kind="mock")
    step = Mock(return_value=more)
    configure = Mock()
    monkeypatch.setattr(tasks, "worker_source", lambda: source)
    monkeypatch.setattr(tasks, "process_step", step)
    monkeypatch.setattr(tasks.sync_page, "configure", configure)

    tasks.sync_page()

    step.assert_called_once_with(
        source,
        poll_seconds=tasks.settings.JIRA_SYNC_INTERVAL_SEC,
        reconcile_seconds=tasks.settings.JIRA_RECONCILE_INTERVAL_SEC,
    )
    configure.assert_called_once_with(schedule_at=None if more else next_due)
    configure.return_value.defer.assert_called_once_with()


def test_watchdog_and_page_completion_coalesce(monkeypatch):
    configure = Mock()
    configure.return_value.defer.side_effect = AlreadyEnqueued()
    monkeypatch.setattr(tasks, "worker_source", lambda: SimpleNamespace(kind="mock"))
    monkeypatch.setattr(tasks, "process_step", Mock(return_value=True))
    monkeypatch.setattr(tasks.sync_page, "configure", configure)

    tasks.sync_page(timestamp=1)
    configure.return_value.defer.assert_called_once_with()


@pytest.mark.django_db(transaction=True)
def test_postgres_only_one_page_can_wait_in_queue():
    if connection.vendor != "postgresql":
        pytest.skip("Для ограничения очереди нужен PostgreSQL")

    tasks.sync_page.defer()
    with pytest.raises(AlreadyEnqueued):
        tasks.sync_page.defer()
