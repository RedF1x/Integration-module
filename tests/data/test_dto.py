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


@pytest.mark.parametrize("labels", ["intern-visible", {"intern-visible": False}, ["intern-visible", 1]])
def test_labels_must_be_list_of_strings(labels):
    data = minimal()
    data["labels"] = labels
    with pytest.raises(DTOError, match="labels"):
        IssueDTO.from_dict(data)


@pytest.mark.parametrize("field_name", ["start_date", "end_date"])
def test_sprint_rejects_invalid_dates(field_name):
    data = minimal()
    data["sprint"] = {"jira_id": "10", "name": "Sprint 1", "state": "active", field_name: "вчера"}
    with pytest.raises(DTOError, match=f"sprint.{field_name}"):
        IssueDTO.from_dict(data)


def test_sprint_accepts_missing_dates():
    data = minimal()
    data["sprint"] = {"jira_id": "10", "name": "Sprint 1", "state": "active",
                      "start_date": None, "end_date": None}
    sprint = IssueDTO.from_dict(data).sprint
    assert sprint.start_date is None and sprint.end_date is None


@pytest.mark.parametrize("value", ["2026-11-11", "2026-11-11T12:00:00"])
@pytest.mark.parametrize("field_name", [
    "updated_at", "comment.created_at", "sprint.start_date", "sprint.end_date",
])
def test_dates_require_timezone(field_name, value):
    data = minimal()
    if field_name == "updated_at":
        data["updated_at"] = value
    elif field_name == "comment.created_at":
        data["comments"] = [{
            "jira_id": "1",
            "author": {"account_id": "x", "display_name": "N"},
            "created_at": value,
        }]
    else:
        data["sprint"] = {
            "jira_id": "10", "name": "Sprint", "state": "active",
            field_name.split(".")[1]: value,
        }
    with pytest.raises(DTOError, match="часовым поясом"):
        IssueDTO.from_dict(data)


@pytest.mark.parametrize("value", [[], None, "issue"])
def test_issue_input_must_be_an_object(value):
    with pytest.raises(DTOError, match="issue"):
        IssueDTO.from_dict(value)


@pytest.mark.parametrize(("field_name", "value"), [
    ("comments", 123), ("comments", 0), ("comments", {}), ("comments", "text"),
    ("links", 123), ("links", False), ("links", {}), ("links", "text"),
    ("custom_fields", 123), ("custom_fields", False),
    ("custom_fields", []), ("custom_fields", "text"),
])
def test_nested_collections_reject_wrong_types(field_name, value):
    data = minimal()
    data[field_name] = value
    with pytest.raises(DTOError, match=field_name):
        IssueDTO.from_dict(data)


def test_nullable_collections_keep_empty_defaults():
    data = minimal()
    data.update(comments=None, links=None, custom_fields=None)
    issue = IssueDTO.from_dict(data)
    assert issue.comments == [] and issue.links == [] and issue.custom_fields == {}


@pytest.mark.parametrize("field_name", ["comments", "links"])
def test_nested_collection_items_must_be_objects(field_name):
    data = minimal()
    data[field_name] = [123]
    with pytest.raises(DTOError):
        IssueDTO.from_dict(data)


@pytest.mark.parametrize("field_name", ["assignee", "sprint"])
@pytest.mark.parametrize("value", [False, {}])
def test_optional_objects_reject_invalid_values(field_name, value):
    data = minimal()
    data[field_name] = value
    with pytest.raises(DTOError):
        IssueDTO.from_dict(data)


@pytest.mark.parametrize("state", ["paused", "", False])
def test_sprint_rejects_unknown_state(state):
    data = minimal()
    data["sprint"] = {"jira_id": "10", "name": "Sprint", "state": state}
    with pytest.raises(DTOError):
        IssueDTO.from_dict(data)


@pytest.mark.parametrize("state", ["future", "active", "closed"])
def test_sprint_accepts_known_state(state):
    data = minimal()
    data["sprint"] = {"jira_id": "10", "name": "Sprint", "state": state}
    assert IssueDTO.from_dict(data).sprint.state == state


@pytest.mark.parametrize("field_name", ["start_date", "end_date"])
@pytest.mark.parametrize("value", [False, 0, ""])
def test_sprint_dates_reject_false_values(field_name, value):
    data = minimal()
    data["sprint"] = {
        "jira_id": "10", "name": "Sprint", "state": "active", field_name: value,
    }
    with pytest.raises(DTOError, match=f"sprint.{field_name}"):
        IssueDTO.from_dict(data)
