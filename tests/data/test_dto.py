import json
from pathlib import Path

import pytest

from jira_integration.dto import DTOError, IssueDTO

SAMPLE = Path(__file__).resolve().parents[2] / "fixtures" / "dto" / "sample.json"


def minimal():
    return {"jira_id": 1, "key": "A-1", "project_key": "A", "summary": "s", "issue_type": "Task",
            "status": {"name": "To Do", "category": "todo"}, "updated_at": "2026-11-04T10:00:00.000+0300"}


def test_minimal_issue_optional_fields_default():
    issue = IssueDTO.from_dict(minimal())
    assert issue.jira_id == "1"
    assert issue.assignee is None and issue.sprint is None
    assert issue.labels == [] and issue.comments == [] and issue.links == []
    assert issue.description_html is None


def test_roundtrip_all_sample_issues():
    data = json.loads(SAMPLE.read_text(encoding="utf-8"))
    for raw in data["issues"]:
        issue = IssueDTO.from_dict(raw)
        assert IssueDTO.from_dict(issue.to_dict()) == issue


def test_missing_required_field():
    data = minimal()
    del data["summary"]
    with pytest.raises(DTOError):
        IssueDTO.from_dict(data)


def test_bad_status_category():
    data = minimal()
    data["status"]["category"] = "weird"
    with pytest.raises(DTOError):
        IssueDTO.from_dict(data)


def test_bad_date():
    data = minimal()
    data["updated_at"] = "вчера"
    with pytest.raises(DTOError):
        IssueDTO.from_dict(data)


def test_hidden_email_becomes_none():
    data = minimal()
    data["assignee"] = {"account_id": "x", "display_name": "N", "email": ""}
    assert IssueDTO.from_dict(data).assignee.email is None


def test_comment_requires_jira_id():
    data = minimal()
    data["comments"] = [{"author": {"account_id": "x", "display_name": "N"},
                         "body_html": "<p>x</p>", "created_at": "2026-11-04T10:00:00+00:00"}]
    with pytest.raises(DTOError):
        IssueDTO.from_dict(data)
