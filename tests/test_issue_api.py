import pytest
from django.urls import reverse
from django.utils import timezone

from jira_integration.models import (
    JiraIssue,
    JiraIssueLink,
    JiraProject,
    JiraStatus,
    ModuleUser,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def intern_user(django_user_model):
    user = django_user_model.objects.create_user(username="issue-intern")
    ModuleUser.objects.create(
        user=user,
        role=ModuleUser.Role.INTERN,
        is_active=True,
        owner_ref="owner-1",
    )
    project = JiraProject.objects.create(
        jira_id="1", project_key="DEMO", name="Демо", is_enabled=True
    )
    status = JiraStatus.objects.create(
        jira_id="1", name="К выполнению", category="todo"
    )
    now = timezone.now()
    issues = {}

    for key, owner in [
        ("DEMO-1", "owner-1"),
        ("DEMO-2", "owner-1"),
        ("DEMO-3", "owner-2"),
    ]:
        issues[key] = JiraIssue.objects.create(
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

    for target in ("DEMO-2", "DEMO-3"):
        JiraIssueLink.objects.create(
            from_issue=issues["DEMO-1"],
            to_key=target,
            link_type="Relates",
            direction="outward",
        )

    return user


def test_issue_api_returns_own_issue_and_visible_links(client, intern_user):
    client.force_login(intern_user)
    url = reverse("jira_integration:api_issue", kwargs={"key": "DEMO-1"})

    response = client.get(url)

    assert response.status_code == 200
    data = response.json()
    assert data["key"] == "DEMO-1"
    assert data["project_key"] == "DEMO"
    assert data["status"]["category"] == "todo"
    assert data["links"] == [{
        "link_type": "Relates",
        "direction": "outward",
        "target_key": "DEMO-2",
    }]
    assert "owner_ref" not in data
    assert isinstance(data["updated_at"], str)
    assert isinstance(data["synced_at"], str)


@pytest.mark.parametrize("key", ["DEMO-3", "DEMO-999"])
def test_issue_api_returns_same_404_for_foreign_and_missing_issue(
    client, intern_user, key
):
    client.force_login(intern_user)
    url = reverse("jira_integration:api_issue", kwargs={"key": key})

    response = client.get(url)

    assert response.status_code == 404
    assert response.json() == {
        "error": "not_found",
        "message": "Задача не найдена.",
    }


@pytest.mark.parametrize(
    ("role", "expected_status", "error"),
    [
        (None, 401, "unauthorized"),
        (ModuleUser.Role.STAFF, 403, "forbidden"),
    ],
)
def test_issue_api_checks_access(client, intern_user, role, expected_status, error):
    if role is not None:
        ModuleUser.objects.filter(user=intern_user).update(role=role)
        client.force_login(intern_user)

    url = reverse("jira_integration:api_issue", kwargs={"key": "DEMO-1"})
    response = client.get(url)

    assert response.status_code == expected_status
    assert response.json()["error"] == error


def test_issue_api_rejects_post(client, intern_user):
    client.force_login(intern_user)
    url = reverse("jira_integration:api_issue", kwargs={"key": "DEMO-1"})

    response = client.post(url)

    assert response.status_code == 405
    assert response["Allow"] == "GET"
    assert response.json()["error"] == "method_not_allowed"