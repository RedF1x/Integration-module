from contextlib import contextmanager
from contextvars import ContextVar

from django.db import connection

LOCK_ID = 7291041182701
_held = ContextVar("jira_sync_lock", default=False)


class SyncBusy(RuntimeError):
    pass


@contextmanager
def sync_lock():
    """Session lock: не держит транзакцию открытой во время HTTP."""
    if connection.vendor != "postgresql":
        raise RuntimeError(
            "Запись sync требует PostgreSQL; для просмотра есть --dry-run"
        )
    if _held.get():
        raise SyncBusy("Синхронизация уже выполняется")
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(%s)", [LOCK_ID])
        acquired = cursor.fetchone()[0]
    if not acquired:
        raise SyncBusy("Синхронизация уже выполняется")
    token = _held.set(True)
    try:
        yield
    finally:
        _held.reset(token)
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_unlock(%s)", [LOCK_ID])
