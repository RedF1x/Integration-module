import pytest
from django.apps import apps
from django.core.management import call_command
from django.db import connection


@pytest.mark.django_db(transaction=True)
def test_initial_migration_can_be_reapplied():
    app = apps.get_app_config("jira_integration")
    expected_tables = {model._meta.db_table for model in app.get_models()}

    assert len(expected_tables) == 11
    assert expected_tables <= set(connection.introspection.table_names())

    call_command("migrate", "jira_integration", "zero", verbosity=0)
    assert expected_tables.isdisjoint(connection.introspection.table_names())

    call_command("migrate", "jira_integration", "0001_initial", verbosity=0)
    assert expected_tables <= set(connection.introspection.table_names())