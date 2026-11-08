import json
from pathlib import Path

import pytest

from jira_integration.dto import DTOError, IssueDTO, ProjectDTO, StatusDTO

SAMPLE = Path(__file__).resolve().parents[2] / "fixtures" / "dto" / "sample.json"


def minimal():
    return {"jira_id": 1, "key": "A-1", "project_key": "A", "summary": "s", "issue_type": "Task",
            "status": {"jira_id": "10000", "name": "To Do", "category": "todo"}, "updated_at": "2026-11-04T10:00:00.000+0300"}


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


def test_status_requires_jira_id():
    data = minimal()
    del data["status"]["jira_id"]
    with pytest.raises(DTOError):
        IssueDTO.from_dict(data)


def test_project_requires_jira_id():
    with pytest.raises(DTOError):
        ProjectDTO.from_dict({"key": "DEMO", "name": "Demo"})
    assert ProjectDTO.from_dict({"jira_id": 10100, "key": "DEMO", "name": "Demo"}).jira_id == "10100"


def test_same_status_name_has_same_jira_id_in_sample():
    data = json.loads(SAMPLE.read_text(encoding="utf-8"))
    seen = {}
    for raw in data["issues"]:
        st = StatusDTO.from_dict(raw["status"])
        assert seen.setdefault(st.name, st.jira_id) == st.jira_id
