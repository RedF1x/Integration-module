import pytest
from django.utils import timezone

from jira_integration.models import (
    JiraFieldDef,
    JiraIssue,
    JiraIssueLink,
    JiraProject,
    JiraStatus,
)
from jira_integration.serializers import serialize_issue

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    ("purpose", "enabled", "expected_fields"),
    [
        ("display", True, {"customfield_100": "Значение"}),
        ("display", False, {}),
        ("owner", True, {}),
        ("policy_flag", True, {}),
        ("intern_description", True, {}),
    ],
)
def test_issue_serialization_filters_fields(purpose, enabled, expected_fields):
    JiraFieldDef.objects.create(
        jira_field_id="customfield_100",
        name="Поле",
        value_type="string",
        purpose=purpose,
        is_enabled=enabled,
    )
    now = timezone.now()
    issue = JiraIssue(
        jira_id="10001",
        issue_key="DEMO-1",
        project=JiraProject(project_key="DEMO"),
        status=JiraStatus(jira_id="10", name="В работе", category="in_progress"),
        summary="Подготовить страницу",
        issue_type="Task",
        owner_ref="internal-owner",
        description_html="<p>Описание пока скрыто</p>",
        custom_fields={
            "customfield_100": "Значение",
            "unknown_field": "Не разрешено",
        },
        updated_jira=now,
        synced_at=now,
    )
    issue.visible_links = [
        JiraIssueLink(to_key="DEMO-2", link_type="Relates", direction="outward")
    ]

    data = serialize_issue(issue)

    assert set(data) == {
        "jira_id", "key", "project_key", "summary", "issue_type",
        "status", "updated_at", "priority", "rank", "assignee",
        "sprint", "labels", "description_html", "custom_fields",
        "comments", "links", "synced_at",
    }
    assert data["key"] == "DEMO-1"
    assert data["project_key"] == "DEMO"
    assert data["status"] == {
        "jira_id": "10",
        "name": "В работе",
        "category": "in_progress",
    }
    assert data["assignee"] is None
    assert data["sprint"] is None
    assert data["description_html"] is None
    assert data["comments"] == []
    assert data["custom_fields"] == expected_fields
    assert data["links"] == [{
        "link_type": "Relates",
        "direction": "outward",
        "target_key": "DEMO-2",
    }]
    assert data["updated_at"] == now
    assert data["synced_at"] == now