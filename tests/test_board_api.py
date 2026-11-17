import pytest
from django.urls import reverse
from django.utils import timezone

from jira_integration.models import (
    JiraIssue,
    JiraProject,
    JiraSprint,
    JiraStatus,
    ModuleUser,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def intern_user(django_user_model):
    user = django_user_model.objects.create_user(username="board-intern")
    ModuleUser.objects.create(
        user=user,
        role=ModuleUser.Role.INTERN,
        is_active=True,
        owner_ref="owner-1",
    )
    return user


def test_board_api_returns_only_own_active_sprint_cards(client, intern_user):
    project = JiraProject.objects.create(
        jira_id="1", project_key="DEMO", name="Демо", is_enabled=True
    )
    status = JiraStatus.objects.create(
        jira_id="1", name="К выполнению", category="todo"
    )
    sprint = JiraSprint.objects.create(
        jira_id="10", project=project, name="Спринт 1", state="active"
    )
    now = timezone.now()

    for key, owner, issue_sprint in [
        ("DEMO-1", "owner-1", sprint),
        ("DEMO-2", "owner-2", sprint),
        ("DEMO-3", "owner-1", None),
    ]:
        JiraIssue.objects.create(
            jira_id=key,
            issue_key=key,
            project=project,
            status=status,
            sprint=issue_sprint,
            summary="Задача",
            issue_type="Task",
            owner_ref=owner,
            updated_jira=now,
            synced_at=now,
        )

    client.force_login(intern_user)
    response = client.get(
        reverse("jira_integration:api_board"),
        {"project_key": "DEMO"},
    )

    assert response.status_code == 200
    data = response.json()
    assert set(data) == {"sprint", "columns", "synced_at"}
    assert data["sprint"] == {
        "jira_id": "10",
        "name": "Спринт 1",
        "state": "active",
        "start_date": None,
        "end_date": None,
    }
    assert len(data["columns"]) == 1
    column = data["columns"][0]
    assert column["status"] == "К выполнению"
    assert column["category"] == "todo"
    assert [card["key"] for card in column["issues"]] == ["DEMO-1"]
    assert isinstance(data["synced_at"], str)


def test_board_api_returns_empty_board(client, intern_user):
    client.force_login(intern_user)

    response = client.get(reverse("jira_integration:api_board"))

    assert response.status_code == 200
    assert response.json() == {
        "sprint": None,
        "columns": [],
        "synced_at": None,
    }


@pytest.mark.parametrize(
    ("role", "expected_status", "error"),
    [
        (None, 401, "unauthorized"),
        (ModuleUser.Role.STAFF, 403, "forbidden"),
    ],
)
def test_board_api_checks_access(client, intern_user, role, expected_status, error):
    if role is not None:
        ModuleUser.objects.filter(user=intern_user).update(role=role)
        client.force_login(intern_user)

    response = client.get(reverse("jira_integration:api_board"))

    assert response.status_code == expected_status
    assert response.json()["error"] == error