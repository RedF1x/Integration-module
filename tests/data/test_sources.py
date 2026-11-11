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
    (tmp_path / "bad.json").write_text(json.dumps({"projects": [], "issues": [{"key": "SECRET-1"}]}), encoding="utf-8")
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


@pytest.mark.parametrize(
    "payload",
    [
        {"id": "1", "key": "DEMO-1", "fields": {}},
        [],
        None,
        {},
        {"projects": []},
        {"issues": []},
        {"projects": {}, "issues": []},
        {"projects": [], "issues": None},
        {"projects": [None], "issues": []},
        {"projects": [], "issues": ["DEMO-1"]},
    ],
)
def test_invalid_file_structure_raises_source_error(tmp_path, payload):
    (tmp_path / "invalid.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )

    with pytest.raises(SourceError):
        FileSource(tmp_path)


def test_valid_empty_file_is_allowed(tmp_path):
    (tmp_path / "empty.json").write_text(
        json.dumps({"projects": [], "issues": []}), encoding="utf-8"
    )

    source = FileSource(tmp_path)

    assert source.projects() == []
    assert list(source.issues()) == []


@pytest.mark.parametrize(("field_name", "value"), [
    ("comments", 123), ("links", 123), ("custom_fields", 123),
    ("comments", [123]), ("links", [123]),
    ("updated_at", "2026-11-11T12:00:00"),
])
def test_invalid_nested_values_raise_source_error(tmp_path, field_name, value):
    sample = get_source()
    issue = sample.issue_detail("DEMO-1").to_dict()
    issue[field_name] = value
    (tmp_path / "invalid.json").write_text(
        json.dumps({"projects": [], "issues": [issue]}), encoding="utf-8"
    )
    with pytest.raises(SourceError):
        FileSource(tmp_path)


@pytest.mark.parametrize("timestamp", [
    "2026-11-11T12:00:00Z",
    "2026-11-11T15:00:00+03:00",
    "2026-11-11T15:00:00+0300",
])
def test_since_filter_handles_offsets_and_includes_boundary(tmp_path, timestamp):
    issue = get_source().issue_detail("DEMO-1").to_dict()
    issue["updated_at"] = timestamp
    (tmp_path / "sample.json").write_text(
        json.dumps({"projects": [], "issues": [issue]}), encoding="utf-8"
    )
    source = FileSource(tmp_path)
    boundary = datetime(2026, 11, 11, 12, tzinfo=timezone.utc)
    assert [item.key for item in source.issues(boundary)] == ["DEMO-1"]
    after = datetime(2026, 11, 11, 12, 0, 1, tzinfo=timezone.utc)
    assert list(source.issues(after)) == []
