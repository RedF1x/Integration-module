from contextlib import nullcontext
from copy import deepcopy
from datetime import timedelta

import pytest
from django.core.management import CommandError, call_command
from django.db import connection
from django.utils import timezone

from jira_integration.models import (
    JiraIssue,
    JiraProject,
    JiraSyncRun,
    JiraVisibilityRule,
)
from jira_integration.queueing.models import SyncCursor
from jira_integration.sources.http import (
    InvalidCursor,
    JiraStatusError,
    JiraUnavailable,
    RetryLater,
)
from jira_integration.sync.paged import process_step
from jira_integration.sync.real_store import RealStore

from .test_queue_sources import make_source

pytestmark = pytest.mark.django_db


@pytest.fixture
def source(raw_source, monkeypatch):
    if connection.vendor == "sqlite":
        monkeypatch.setattr(RealStore, "lock", lambda self: nullcontext())
    project = JiraProject.objects.create(
        jira_id="10000", project_key="SCRUM", name="Test", is_enabled=True
    )
    JiraVisibilityRule.objects.create(
        project=project,
        source="label",
        expected_value="intern-visible",
        is_enabled=True,
    )
    return raw_source


def complete(source):
    for _ in range(10):
        if not process_step(source):
            return SyncCursor.objects.get(pk=source.kind)
    pytest.fail("Обход не завершён")


def make_due(full=False):
    changes = {"next_due": timezone.now() - timedelta(seconds=1)}
    if full:
        changes["last_full"] = None
    SyncCursor.objects.update(**changes)


def test_worker_cannot_reconcile_mock_into_rest_database(source):
    SyncCursor.objects.create(pk="rest")
    with pytest.raises(ValueError, match="разные базы"):
        process_step(source)
    assert not SyncCursor.objects.filter(pk="mock").exists()
    assert not JiraSyncRun.objects.exists()


def test_two_hundred_issues_use_four_search_pages(source, monkeypatch):
    sample = next(source.raw_issues())
    calls = []

    def page(since, until, token, **kwargs):
        start = int(token or 0)
        calls.append(start)
        rows = []
        for number in range(start + 1, start + 51):
            raw = deepcopy(sample)
            raw.update(id=str(20000 + number), key=f"SCRUM-{number}")
            rows.append(raw)
        return rows, str(start + 50) if start < 150 else None

    monkeypatch.setattr(source, "issue_page", page)
    complete(source)
    assert calls == [0, 50, 100, 150]
    assert JiraIssue.objects.count() == 200
    assert JiraSyncRun.objects.get().created_count == 200


def test_restart_resumes_next_page_without_advancing_watermark(source, monkeypatch):
    issues = list(source.raw_issues())
    visited = []

    def page(since, until, token, **kwargs):
        visited.append(token)
        if token is None:
            return issues[:1], "second"
        return issues[1:], None

    monkeypatch.setattr(source, "issue_page", page)
    assert process_step(source)
    state = SyncCursor.objects.get()
    assert state.page_token == "second"
    assert state.watermark is None
    assert JiraIssue.objects.count() == 1
    state = complete(source)
    assert visited == [None, "second"]
    assert JiraIssue.objects.count() == 8
    run = JiraSyncRun.objects.get()
    assert run.status == "success" and run.created_count == 8
    assert state.watermark == run.started_at
    assert not process_step(source)
    assert visited == [None, "second"]


def test_incremental_uses_completed_window_and_no_full_recheck(source, monkeypatch):
    state = complete(source)
    before = state.watermark
    make_due()
    calls = []

    def page(since, until, token, **kwargs):
        calls.append((since, until, token))
        return [], None

    monkeypatch.setattr(source, "issue_page", page)
    monkeypatch.setattr(
        source, "bulk_issues", lambda *a, **kw: pytest.fail("Не время сверки")
    )
    state = complete(source)
    since, until, token = calls[0]
    assert since == before - timedelta(seconds=source.config.overlap_seconds)
    assert until == state.watermark.replace(second=0, microsecond=0)
    assert token is None
    assert JiraSyncRun.objects.latest("pk").mode == "incremental"


def test_partial_then_confirmed_bulk_absence(source, monkeypatch):
    state = complete(source)
    before = state.watermark
    make_due(full=True)
    target = JiraIssue.objects.first()
    remaining = [row for row in source.raw_issues() if row["id"] != target.jira_id]
    monkeypatch.setattr(source, "issue_page", lambda *a, **kw: (remaining, None))
    monkeypatch.setattr(source, "bulk_issues", lambda *a, **kw: [])
    assert process_step(source)
    with pytest.raises(RuntimeError):
        process_step(source)
    assert JiraIssue.objects.filter(pk=target.pk).exists()
    assert SyncCursor.objects.get().watermark == before

    def confirm(ids, **kwargs):
        assert ids == [target.jira_id]
        yield [], set(ids)

    monkeypatch.setattr(source, "bulk_issues", confirm)
    make_due(full=True)
    state = complete(source)
    assert state.watermark > before
    assert not JiraIssue.objects.filter(pk=target.pk).exists()
    assert JiraSyncRun.objects.latest("pk").deleted_count == 1


def test_invalid_token_restarts_and_rate_limit_preserves_page(source, monkeypatch):
    row = source.raw_issue_detail("SCRUM-5")

    def page(since, until, token, **kwargs):
        if token:
            raise InvalidCursor("expired")
        return [row], "stale"

    monkeypatch.setattr(source, "issue_page", page)
    assert process_step(source)
    assert process_step(source)
    assert SyncCursor.objects.get().cursor_restarts == 1
    assert process_step(source)

    def throttled(*args, **kwargs):
        raise RetryLater(180)

    monkeypatch.setattr(source, "issue_page", throttled)
    now = timezone.now()
    assert not process_step(source)
    state = SyncCursor.objects.get()
    assert state.page_token == "stale" and state.next_due >= now + timedelta(
        seconds=180
    )
    assert not process_step(source)
    assert JiraIssue.objects.count() == 1
    assert JiraSyncRun.objects.get().status == "running"


def test_failed_page_still_closes_previous_owners(source, monkeypatch):
    complete(source)
    make_due()
    row = source.raw_issue_detail("SCRUM-5")
    row["fields"]["assignee"]["accountId"] = "replacement"
    del row["fields"]["summary"]
    monkeypatch.setattr(source, "issue_page", lambda *a, **kw: ([row], None))
    assert not process_step(source)
    assert JiraIssue.objects.get(issue_key="SCRUM-5").owner_ref is None
    assert JiraSyncRun.objects.latest("pk").status == "failed"


@pytest.mark.parametrize("failure", [RetryLater(180), JiraUnavailable("offline")])
def test_confirmed_revocations_survive_later_failure(source, monkeypatch, failure):
    state = complete(source)
    make_due(full=True)
    issues = list(JiraIssue.objects.order_by("jira_id")[:3])
    revoked, gone, unknown = [i.jira_id for i in issues]
    row = source.raw_issue_detail(issues[0].issue_key)
    row["fields"]["labels"] = []
    rows = [r for r in source.raw_issues() if r["id"] not in {revoked, gone, unknown}]
    monkeypatch.setattr(source, "issue_page", lambda *a, **kw: (rows, None))
    assert process_step(source)
    rest = make_source()
    original_bulk = source.bulk_issues
    monkeypatch.setattr(rest, "_fields", lambda fields: [])

    def request(method, path, **kwargs):
        if method == "POST":
            return {"issues": [row]}
        if path.endswith("/" + gone):
            raise JiraStatusError(404)
        raise failure

    monkeypatch.setattr(rest.http, "request", request)
    monkeypatch.setattr(source, "bulk_issues", rest.bulk_issues)
    assert not process_step(source)
    assert not JiraIssue.objects.filter(jira_id__in=[revoked, gone]).exists()
    assert JiraIssue.objects.filter(jira_id=unknown).exists()
    cursor = SyncCursor.objects.get()
    assert cursor.phase == "verify" and cursor.reconcile_pk == 0
    assert cursor.watermark == state.watermark
    assert cursor.run.deleted_count == 2
    monkeypatch.setattr(source, "bulk_issues", original_bulk)
    make_due()
    complete(source)
    assert JiraSyncRun.objects.latest("pk").status == "success"


@pytest.mark.parametrize("bad_field", ["priority", "labels"])
def test_bad_issue_does_not_block_next_page_and_is_retried(
    source, monkeypatch, bad_field
):
    before = complete(source).watermark
    first, second = list(JiraIssue.objects.order_by("pk")[:2])
    bad = source.raw_issue_detail(first.issue_key)
    good = source.raw_issue_detail(second.issue_key)
    good["fields"]["summary"] = "updated second page"
    damaged = deepcopy(bad)
    del damaged["fields"][bad_field]
    make_due()

    def page(since, until, token, **kwargs):
        return ([good], None) if token else ([damaged], "next")

    monkeypatch.setattr(source, "issue_page", page)
    state = complete(source)
    run = JiraSyncRun.objects.latest("pk")
    assert run.status == "failed" and run.failed_count == 1
    assert run.error_message == bad["id"] and state.watermark == before
    assert JiraIssue.objects.get(pk=second.pk).summary == "updated second page"
    assert JiraIssue.objects.filter(
        pk=first.pk, owner_ref=first.owner_ref
    ).exists() == (bad_field == "priority")
    make_due()
    monkeypatch.setattr(source, "issue_page", lambda *a, **kw: ([bad], None))
    assert complete(source).watermark > before
    assert JiraIssue.objects.filter(
        jira_id=bad["id"], owner_ref=first.owner_ref
    ).exists()


def test_manual_command_keeps_background_run_and_next_page(source, monkeypatch):
    rows = list(source.raw_issues())

    def page(since, until, token, **kwargs):
        return (rows[1:], None) if token else (rows[:1], "next")

    monkeypatch.setattr(source, "issue_page", page)
    monkeypatch.setattr(
        "jira_integration.management.commands.sync_jira.get_source", lambda: source
    )
    assert process_step(source)
    run = JiraSyncRun.objects.get()
    with pytest.raises(CommandError, match="Фоновая синхронизация"):
        call_command("sync_jira", "--full")
    cursor = SyncCursor.objects.get()
    assert cursor.run_id == run.pk and cursor.page_token == "next"
    assert cursor.run.status == "running"
    complete(source)
    assert JiraSyncRun.objects.get().status == "success"
