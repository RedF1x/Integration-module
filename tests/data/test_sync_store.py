from contextlib import nullcontext
from copy import deepcopy
from dataclasses import replace
from io import StringIO

import pytest
from django.core.management import call_command
from django.db import connection

from jira_integration.models import (
    JiraComment,
    JiraIssue,
    JiraProject,
    JiraSprint,
    JiraSyncRun,
    JiraUser,
    JiraVisibilityRule,
)
from jira_integration.sources.base import SourceError
from jira_integration.sync.real_store import RealStore
from jira_integration.sync.service import run_sync

pytestmark = pytest.mark.django_db


class SQLiteTestStore(RealStore):
    """SQLite проверяет данные/транзакции, не имитирует PostgreSQL lock."""

    def lock(self):
        return nullcontext()


@pytest.fixture
def store():
    project = JiraProject.objects.create(
        jira_id="10000", project_key="SCRUM", name="Test", is_enabled=True
    )
    JiraVisibilityRule.objects.create(
        project=project,
        source="label",
        expected_value="intern-visible",
        is_enabled=True,
    )
    return SQLiteTestStore("mock")


def test_database_repeat_owner_and_private_text(raw_source, store):
    first = run_sync(raw_source, store=store)
    ids = list(JiraIssue.objects.order_by("pk").values_list("pk", flat=True))
    second = run_sync(raw_source, store=store)
    assert first.created == 8 and second.updated == 8
    assert ids == list(JiraIssue.objects.order_by("pk").values_list("pk", flat=True))
    assert JiraIssue.objects.exclude(owner_ref="test-account-1").count() == 0
    assert JiraIssue.objects.exclude(description_html=None).count() == 0
    assert JiraComment.objects.count() == 0
    assert JiraIssue.objects.get(issue_key="SCRUM-5").priority_order is not None
    assert JiraSprint.objects.count() == 4
    assert all(
        r.status == "success" and r.source == "mock" for r in JiraSyncRun.objects.all()
    )


def test_owner_change_and_explicit_revoke(raw_source, store, monkeypatch):
    run_sync(raw_source, store=store)
    raw = raw_source.raw_issue_detail("SCRUM-5")
    raw["fields"]["assignee"]["accountId"] = "test-account-2"
    monkeypatch.setattr(raw_source, "raw_issues", lambda *a, **k: iter([raw]))
    run_sync(raw_source, store=store)
    issue = JiraIssue.objects.get(issue_key="SCRUM-5")
    assert issue.owner_ref == "test-account-2"
    raw["fields"]["labels"].remove("intern-visible")
    result = run_sync(raw_source, store=store)
    assert result.deleted == 1 and not JiraIssue.objects.filter(pk=issue.pk).exists()
    assert JiraIssue.objects.count() == 7  # full НЕ удаляет по отсутствию
    assert JiraSyncRun.objects.latest("pk").deleted_count == 1


def test_denied_project_or_empty_rules_remove_old_rows(raw_source, store):
    run_sync(raw_source, store=store)
    JiraVisibilityRule.objects.update(is_enabled=False)
    result = run_sync(raw_source, store=store)
    assert result.deleted == 8 and JiraIssue.objects.count() == 0


def test_disabled_text_cleans_previous_values_even_if_jira_fails(
    raw_source, store, monkeypatch
):
    run_sync(raw_source, store=store)
    issue = JiraIssue.objects.get(issue_key="SCRUM-5")
    issue.description_html = "old private text"
    issue.custom_fields = {"customfield_999": "old private value"}
    issue.save()
    JiraComment.objects.create(
        jira_id="private",
        issue=issue,
        body_html="private",
        created_jira=issue.updated_jira,
    )

    def unavailable():
        raise SourceError("SECRET")

    monkeypatch.setattr(raw_source, "catalog", unavailable)
    result = run_sync(raw_source, store=store)
    issue.refresh_from_db()
    assert result.status == "failed" and JiraIssue.objects.count() == 8
    assert issue.description_html is None and issue.custom_fields == {}
    assert not issue.comments.exists()


def test_comment_pages_incomplete_do_not_replace_saved_list(
    raw_source, store, monkeypatch
):
    raw = raw_source.raw_issue_detail("SCRUM-11")
    monkeypatch.setattr(raw_source, "raw_issues", lambda *a, **k: iter([raw]))
    raw_source.config = replace(raw_source.config, comments=True)
    assert run_sync(raw_source, store=store).created == 1
    assert JiraComment.objects.count() == 4

    def incomplete(key):
        raise SourceError("partial")

    monkeypatch.setattr(raw_source, "comments", incomplete)
    result = run_sync(raw_source, store=store)
    assert result.failed == 1 and JiraComment.objects.count() == 4


def test_conflicting_issue_rolls_back_related_user_but_continues(
    raw_source, store, monkeypatch
):
    first = raw_source.raw_issue_detail("SCRUM-5")
    second = raw_source.raw_issue_detail("SCRUM-8")
    third = raw_source.raw_issue_detail("SCRUM-15")
    second["key"] = first["key"]
    second["fields"]["assignee"]["accountId"] = "rolled-back"
    monkeypatch.setattr(
        raw_source, "raw_issues", lambda *a, **k: iter([first, second, third])
    )
    result = run_sync(raw_source, store=store)
    assert result.created == 2 and result.failed == 1
    assert not JiraUser.objects.filter(account_id="rolled-back").exists()
    assert JiraIssue.objects.filter(issue_key="SCRUM-15").exists()
    assert store.last_success() is None


def test_dry_run_no_writes_or_sync_runs(raw_source, store):
    result = run_sync(raw_source, store=store, dry_run=True)
    assert result.processed == 12
    assert not JiraIssue.objects.exists() and not JiraSyncRun.objects.exists()
    output = StringIO()
    call_command("sync_jira", "--dry-run", stdout=output)
    assert "dry-run success" in output.getvalue()
    assert not JiraSyncRun.objects.exists()


def test_cursor_ignores_failed_and_other_source_runs(raw_source, store):
    run_sync(raw_source, store=store)
    success = store.last_success()
    JiraSyncRun.objects.create(source="mock", mode="incremental", status="failed")
    JiraSyncRun.objects.create(source="rest", mode="full", status="success")
    assert store.last_success().pk == success.pk


def test_abandoned_run_is_failed_when_new_holder_gets_lock(raw_source, store):
    abandoned = JiraSyncRun.objects.create(source="mock", mode="full")
    run_sync(raw_source, store=store)
    abandoned.refresh_from_db()
    assert abandoned.status == "failed" and abandoned.error_code == "interrupted"


def test_service_lock_not_silently_disabled_for_sqlite(raw_source):
    if connection.vendor != "sqlite":
        pytest.skip("SQLite-specific guard")
    with pytest.raises(RuntimeError, match="PostgreSQL"):
        run_sync(raw_source)
    assert not JiraSyncRun.objects.exists()


def test_comment_collision_is_atomic(raw_source, store):
    from jira_integration.normalizer.issues import normalize
    from jira_integration.policy.rules import Decision

    policy = store.policy()
    catalog = raw_source.catalog()
    store.refresh_catalog(catalog)
    raw = raw_source.raw_issue_detail("SCRUM-11")
    config = replace(raw_source.config, comments=True)
    dto = normalize(raw, catalog, policy, config, raw_source.comments("SCRUM-11"))
    store.upsert_allowed(dto, policy.evaluate(raw), catalog, raw)
    duplicate = replace(dto, jira_id="different", key="SCRUM-999")
    with pytest.raises(ValueError):
        store.upsert_allowed(
            duplicate,
            Decision("different", "test-account-1", True),
            catalog,
            deepcopy(raw),
        )
    assert not JiraIssue.objects.filter(jira_id="different").exists()
    assert JiraComment.objects.count() == 4


@pytest.mark.parametrize("failure", ["comments", "normalization", "write"])
def test_changed_owner_loses_access_even_when_refresh_fails(
    raw_source, store, monkeypatch, failure
):
    run_sync(raw_source, store=store)
    raw = raw_source.raw_issue_detail("SCRUM-5")
    raw["fields"]["assignee"]["accountId"] = "new-owner"
    monkeypatch.setattr(raw_source, "raw_issues", lambda *a, **k: iter([raw]))
    if failure == "comments":
        raw_source.config = replace(raw_source.config, comments=True)

        def unavailable(key):
            raise SourceError("unavailable")

        monkeypatch.setattr(raw_source, "comments", unavailable)
    elif failure == "normalization":
        del raw["fields"]["summary"]
    else:
        raw["key"] = "SCRUM-8"  # Коллизия с другой сохранённой задачей.

    result = run_sync(raw_source, store=store)
    issue = JiraIssue.objects.get(issue_key="SCRUM-5")
    assert result.status == "failed"
    assert issue.owner_ref is None
    assert issue.summary  # Данные сохраняются, но никому не выдаются.


def test_owner_change_dry_run_preserves_owner_then_success_updates_it(
    raw_source, store, monkeypatch
):
    run_sync(raw_source, store=store)
    raw = raw_source.raw_issue_detail("SCRUM-5")
    raw["fields"]["assignee"]["accountId"] = "new-owner"
    monkeypatch.setattr(raw_source, "raw_issues", lambda *a, **k: iter([raw]))
    assert run_sync(raw_source, store=store, dry_run=True).status == "success"
    assert JiraIssue.objects.get(issue_key="SCRUM-5").owner_ref == "test-account-1"
    assert run_sync(raw_source, store=store).status == "success"
    assert JiraIssue.objects.get(issue_key="SCRUM-5").owner_ref == "new-owner"


def test_explicit_denial_revokes_even_without_unrelated_assignee(
    raw_source, store, monkeypatch
):
    run_sync(raw_source, store=store)
    raw = raw_source.raw_issue_detail("SCRUM-5")
    raw["fields"]["labels"].remove("intern-visible")
    del raw["fields"]["assignee"]
    monkeypatch.setattr(raw_source, "raw_issues", lambda *a, **k: iter([raw]))
    result = run_sync(raw_source, store=store)
    assert result.deleted == 1
    assert not JiraIssue.objects.filter(issue_key="SCRUM-5").exists()
