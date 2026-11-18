from contextlib import nullcontext
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from jira_integration.policy.rules import Policy, Rule
from jira_integration.sources.base import SourceError
from jira_integration.sync.service import run_sync


class MemoryStore:
    def __init__(self):
        self.issues = {}
        self.runs = []
        self.current_policy = Policy(True, rules=(Rule("label", "intern-visible"),))
        self.last = None

    def lock(self):
        return nullcontext()

    def policy(self):
        return self.current_policy

    def last_success(self):
        return self.last

    def start_run(self, mode):
        self.runs.append({"mode": mode})
        return len(self.runs) - 1

    def finish_run(self, run_id, result):
        self.runs[run_id]["status"] = result.status

    def apply_local_restrictions(self, policy, config):
        return 0

    def refresh_catalog(self, catalog):
        self.catalog = catalog

    def stored_keys(self):
        return [(identity, dto.key) for identity, dto in self.issues.items()]

    def close_previous_owner(self, decision):
        existing = self.issues.get(decision.jira_id)
        if existing and existing.assignee.account_id != decision.owner_ref:
            self.issues.pop(decision.jira_id)

    def upsert_allowed(self, dto, decision, catalog, raw):
        assert decision.allowed
        created = dto.jira_id not in self.issues
        self.issues[dto.jira_id] = dto
        return created

    def revoke(self, identity):
        return int(self.issues.pop(identity, None) is not None)


def test_full_and_repeat_are_idempotent(raw_source):
    store = MemoryStore()
    first = run_sync(raw_source, store=store)
    second = run_sync(raw_source, store=store)
    assert (first.processed, first.created, first.denied, first.failed) == (12, 8, 4, 0)
    assert (second.created, second.updated) == (0, 8)


def test_dry_run_reads_policy_without_writing(raw_source):
    store = MemoryStore()
    result = run_sync(raw_source, store=store, dry_run=True)
    assert result.processed == 12 and result.denied == 4
    assert not store.issues and not store.runs
    assert not hasattr(store, "catalog")


def test_broken_page_does_not_delete_missing_data_or_report_success(
    raw_source, monkeypatch
):
    store = MemoryStore()
    run_sync(raw_source, store=store)
    existing = set(store.issues)

    def broken(*args, **kwargs):
        yield raw_source.raw_issue_detail("SCRUM-5")
        raise SourceError("SECRET response")

    # Сначала сохраним raw, чтобы подмена итератора не вызвала рекурсию detail.
    raw = raw_source.raw_issue_detail("SCRUM-5")
    monkeypatch.setattr(raw_source, "raw_issue_detail", lambda *a, **k: raw)
    monkeypatch.setattr(raw_source, "raw_issues", broken)
    result = run_sync(raw_source, store=store)
    assert result.status == "failed" and set(store.issues) == existing
    assert result.errors == ["source: SourceError"]
    assert store.runs[-1]["status"] == "failed"


def test_bad_issue_does_not_stop_following_issues(raw_source, monkeypatch):
    values = list(raw_source.raw_issues())
    del values[0]["fields"]["summary"]
    monkeypatch.setattr(raw_source, "raw_issues", lambda *a, **k: iter(values))
    store = MemoryStore()
    result = run_sync(raw_source, store=store)
    assert (result.created, result.failed) == (7, 1)
    assert any(i.key == "SCRUM-15" for i in store.issues.values())


def test_incremental_uses_successful_start_and_rechecks_stored_data(
    raw_source, monkeypatch
):
    store = MemoryStore()
    run_sync(raw_source, store=store)
    store.last = SimpleNamespace(started_at=datetime(2026, 11, 17, 12, tzinfo=UTC))
    detail = raw_source.raw_issue_detail
    requested = []
    seen_since = []

    def changed(since, **kwargs):
        seen_since.append(since)
        return iter([])

    def recheck(key, **kwargs):
        requested.append(key)
        # Оригинальный метод читает исходный итератор; используем независимый source.
        return saved[key]

    saved = {i.key: detail(i.key) for i in store.issues.values()}
    saved["SCRUM-5"]["fields"]["labels"].remove("intern-visible")
    monkeypatch.setattr(raw_source, "raw_issues", changed)
    monkeypatch.setattr(raw_source, "raw_issue_detail", recheck)
    result = run_sync(
        raw_source, "incremental", store=store, since=datetime(2026, 11, 18, tzinfo=UTC)
    )
    assert seen_since == [datetime(2026, 11, 17, 11, 55, tzinfo=UTC)]
    assert len(requested) == 8 and result.deleted == 1 and result.updated == 7


def test_incremental_requires_baseline(raw_source):
    store = MemoryStore()
    with pytest.raises(ValueError, match="full"):
        run_sync(raw_source, "incremental", store=store)
    assert store.runs == []


def test_interrupt_is_failed_not_success(raw_source, monkeypatch):
    def stop():
        raise KeyboardInterrupt()

    monkeypatch.setattr(raw_source, "catalog", stop)
    store = MemoryStore()
    with pytest.raises(KeyboardInterrupt):
        run_sync(raw_source, store=store)
    assert store.runs[-1]["status"] == "failed"


def test_legacy_dto_cannot_bypass_policy(raw_source):
    from jira_integration.sources import FileSource

    with pytest.raises(ValueError, match="raw"):
        run_sync(FileSource(raw_source.root.parent / "dto"))
