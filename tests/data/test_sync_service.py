from pathlib import Path

import pytest

from jira_integration.sources import FileSource, SourceError
from jira_integration.sync.service import run_sync

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "dto"


class MemoryStore:
    def __init__(self):
        self.projects = {}
        self.issues = {}
        self.runs = []

    def upsert_project(self, project):
        self.projects[project.key] = project

    def upsert_issue(self, issue):
        assert issue.project_key in self.projects
        created = issue.jira_id not in self.issues
        self.issues[issue.jira_id] = issue
        return created

    def start_run(self, mode):
        self.runs.append({"mode": mode})
        return len(self.runs) - 1

    def finish_run(self, run_id, result):
        self.runs[run_id]["status"] = result.status


def test_sync_writes_project_before_issues():
    store = MemoryStore()
    result = run_sync(FileSource(FIXTURES), "full", store=store)

    assert store.projects["DEMO"].jira_id == "10100"
    assert len(store.issues) == 4
    assert (result.processed, result.created, result.updated, result.failed) == (
        4,
        4,
        0,
        0,
    )
    assert store.runs[0]["status"] == "success"


def test_dry_run_does_not_use_store():
    store = MemoryStore()
    result = run_sync(FileSource(FIXTURES), "full", store=store, dry_run=True)

    assert (result.processed, result.created, result.updated, result.failed) == (
        4,
        0,
        0,
        0,
    )
    assert not store.projects and not store.issues and not store.runs


def test_source_failure_after_an_issue_marks_run_failed(monkeypatch):
    source = FileSource(FIXTURES)
    store = MemoryStore()

    def broken_issues():
        yield source.issue_detail("DEMO-1")
        raise SourceError("Содержимое ошибочного ответа")

    monkeypatch.setattr(source, "issues", broken_issues)
    result = run_sync(source, "full", store=store)

    assert (result.created, result.failed) == (1, 1)
    assert result.errors == ["source: SourceError"]
    assert store.runs[0]["status"] == "failed"


def test_incremental_mode_rejected_before_writing():
    store = MemoryStore()
    with pytest.raises(ValueError, match="full"):
        run_sync(FileSource(FIXTURES), "incremental", store=store)
    assert not store.runs
