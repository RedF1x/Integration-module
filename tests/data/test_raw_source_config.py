import json

import pytest

from jira_integration.sources import get_source
from jira_integration.sources.base import SourceError
from jira_integration.sources.config import DataConfig
from jira_integration.sources.raw_file_source import RawFileSource


def test_factory_defaults_to_raw_pipeline():
    source = get_source()
    assert isinstance(source, RawFileSource)
    assert len(list(source.raw_issues())) == 12


@pytest.mark.parametrize(
    "name,value",
    [
        ("OWNER_SOURCE", "label"),
        ("JIRA_PROJECT_KEYS", "OTHER"),
        ("JIRA_BOARD_ID", "2"),
        ("JIRA_INCLUDE_DESCRIPTION", "maybe"),
        ("JIRA_OVERLAP_SECONDS", "-1"),
        ("JIRA_BOARD_ID", "invalid"),
    ],
)
def test_unsupported_config_fails_closed(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(SourceError):
        DataConfig.from_env()


def test_manifest_rejects_path_traversal_and_duplicate_issues(tmp_path, raw_source):
    manifest = dict(raw_source.manifest)
    manifest["project"] = "../private.json"
    path = tmp_path / "sprint2.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(SourceError):
        RawFileSource(path, DataConfig()).catalog()
    raw_source.manifest["issues"] = ["issue_active.json", "issue_active.json"]
    with pytest.raises(SourceError, match="Повтор"):
        list(raw_source.raw_issues())


def test_comment_manifest_missing_last_page_is_error(raw_source):
    raw_source.manifest["comments"]["SCRUM-11"].pop()
    with pytest.raises(SourceError, match="страниц"):
        raw_source.comments("SCRUM-11")
