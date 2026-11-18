import pytest
from django.urls import reverse
from django.utils import timezone

from jira_integration.models import JiraIssue, JiraProject, JiraStatus, ModuleUser

pytestmark = pytest.mark.django_db


@pytest.fixture
def intern_user(django_user_model):
    user = django_user_model.objects.create_user(username="api-intern")
    ModuleUser.objects.create(
        user=user,
        role=ModuleUser.Role.INTERN,
        is_active=True,
        owner_ref="owner-1",
    )
    return user


def test_backlog_api_returns_only_own_cards(client, intern_user):
    project = JiraProject.objects.create(
        jira_id="1", project_key="DEMO", name="Демо", is_enabled=True
    )
    status = JiraStatus.objects.create(
        jira_id="1", name="К выполнению", category="todo"
    )
    now = timezone.now()
    for key, owner in [("DEMO-1", "owner-1"), ("DEMO-2", "owner-2")]:
        JiraIssue.objects.create(
            jira_id=key,
            issue_key=key,
            project=project,
            status=status,
            summary="Задача",
            issue_type="Task",
            owner_ref=owner,
            updated_jira=now,
            synced_at=now,
        )

    client.force_login(intern_user)
    response = client.get(reverse("jira_integration:api_backlog"))

    assert response.status_code == 200
    data = response.json()
    assert set(data) == {"count", "results", "synced_at"}
    assert data["count"] == 1
    assert data["results"] == [{
        "key": "DEMO-1",
        "summary": "Задача",
        "status": "К выполнению",
        "issue_type": "Task",
        "priority": None,
        "assignee": None,
    }]
    assert isinstance(data["synced_at"], str)


def test_backlog_api_denies_anonymous_user(client):
    response = client.get(reverse("jira_integration:api_backlog"))

    assert response.status_code == 401
    assert response.json()["error"] == "unauthorized"


def test_backlog_api_denies_staff(client, intern_user):
    ModuleUser.objects.filter(user=intern_user).update(role=ModuleUser.Role.STAFF)
    client.force_login(intern_user)

    response = client.get(reverse("jira_integration:api_backlog"))

    assert response.status_code == 403
    assert response.json()["error"] == "forbidden"


@pytest.mark.parametrize(
    ("params", "expected_status", "error"),
    [
        ({"page": "abc"}, 400, "invalid_page"),
        ({"page": "0"}, 400, "invalid_page"),
        ({"page": "2"}, 404, "not_found"),
        ({"sort": "unknown"}, 400, "invalid_sort"),
        ({"unknown": "value"}, 400, "invalid_parameters"),
    ],
)
def test_backlog_api_parameter_errors(
    client, intern_user, params, expected_status, error
):
    client.force_login(intern_user)

    response = client.get(reverse("jira_integration:api_backlog"), params)

    assert response.status_code == expected_status
    assert response.json()["error"] == error
    assert response.json()["message"]


def test_backlog_api_rejects_post(client, intern_user):
    client.force_login(intern_user)

    response = client.post(reverse("jira_integration:api_backlog"))

    assert response.status_code == 405
    assert response["Allow"] == "GET"
    assert response.json()["error"] == "method_not_allowed"