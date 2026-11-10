import json
from datetime import datetime, timezone

import pytest

from jira_integration.sources import FileSource, SourceError, get_source


def test_file_source_reads_sample():
    src = get_source()  # по умолчанию mock -> fixtures/dto
    assert isinstance(src, FileSource)
    assert [p.key for p in src.projects()] == ["DEMO"]
    assert len(list(src.issues())) == 4
    assert src.issue_detail("DEMO-2").status.category == "in_progress"
    assert src.issue_detail("NOPE-1") is None
    assert [s.jira_id for s in src.sprints("DEMO")] == ["10"]


def test_since_filter():
    src = get_source()
    since = datetime(2026, 11, 5, tzinfo=timezone.utc)
    assert sorted(i.key for i in src.issues(since)) == ["DEMO-2", "DEMO-4"]


def test_missing_dir(tmp_path):
    with pytest.raises(SourceError):
        FileSource(tmp_path / "nope")


def test_broken_file_does_not_leak_content(tmp_path):
    (tmp_path / "bad.json").write_text(json.dumps({"issues": [{"key": "SECRET-1"}]}), encoding="utf-8")
    with pytest.raises(SourceError) as info:
        FileSource(tmp_path)
    assert "SECRET" not in str(info.value)


def test_factory_unknown_and_rest(monkeypatch):
    monkeypatch.setenv("JIRA_SOURCE", "wat")
    with pytest.raises(SourceError):
        get_source()
    monkeypatch.setenv("JIRA_SOURCE", "rest")
    with pytest.raises(SourceError):
        get_source()
