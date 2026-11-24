import pytest
from django.db import connection

from jira_integration.sync.locking import LOCK_ID, SyncBusy, sync_lock


@pytest.mark.django_db(transaction=True)
def test_postgres_lock_blocks_an_independent_connection_and_releases_after_error():
    if connection.vendor != "postgresql":
        pytest.skip("Нужен PostgreSQL: SQLite не проверяет advisory locks")
    import psycopg

    params = connection.get_connection_params()
    with psycopg.connect(**params, autocommit=True) as other:
        with pytest.raises(ValueError), sync_lock():
            with other.cursor() as cursor:
                cursor.execute("SELECT pg_try_advisory_lock(%s)", [LOCK_ID])
                assert cursor.fetchone()[0] is False
            with pytest.raises(SyncBusy), sync_lock():
                pass
            raise ValueError("test")
        with other.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(%s)", [LOCK_ID])
            assert cursor.fetchone()[0] is True
            cursor.execute("SELECT pg_advisory_unlock(%s)", [LOCK_ID])
