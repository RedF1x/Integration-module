import pytest
from django.urls import reverse
from django.utils import timezone

from jira_integration.models import JiraIssue, JiraProject, JiraStatus, ModuleUser

pytestmark = pytest.mark.django_db


@pytest.fixture
def issue_setup(django_user_model):
    user = django_user_model.objects.create_user(username="page-intern")
    profile = ModuleUser.objects.create(
        user=user,
        role=ModuleUser.Role.INTERN,
        is_active=True,
        owner_ref="owner-1",
    )
    project = JiraProject.objects.create(
        jira_id="1", project_key="DEMO", name="Demo", is_enabled=True
    )
    status = JiraStatus.objects.create(
        jira_id="1", name="To Do", category="todo"
    )
    now = timezone.now()
    for key, owner in [("DEMO-1", "owner-1"), ("DEMO-2", "owner-2")]:
        JiraIssue.objects.create(
            jira_id=key,
            issue_key=key,
            project=project,
            status=status,
            summary="Тестовая задача",
            issue_type="Task",
            owner_ref=owner,
            updated_jira=now,
            synced_at=now,
        )
    return user, profile, project


def test_anonymous_issue_page_redirects_to_login(client):
    url = reverse("jira_integration:issue", args=["DEMO-1"])

    response = client.get(url)

    assert response.status_code == 302
    assert response.url == f"{reverse('jira_integration:login')}?next={url}"


def test_own_issue_page_contains_api_url(client, issue_setup):
    user, _, _ = issue_setup
    client.force_login(user)

    response = client.get(reverse("jira_integration:issue", args=["DEMO-1"]))

    assert response.status_code == 200
    html = response.content.decode()
    assert 'id="jira-issue"' in html
    assert reverse("jira_integration:api_issue", args=["DEMO-1"]) in html


@pytest.mark.parametrize("key", ["DEMO-2", "DEMO-999"])
def test_foreign_or_missing_issue_page_returns_404(client, issue_setup, key):
    user, _, _ = issue_setup
    client.force_login(user)

    response = client.get(reverse("jira_integration:issue", args=[key]))

    assert response.status_code == 404
    assert 'id="jira-issue"' not in response.content.decode()


def test_disabled_project_issue_page_returns_404(client, issue_setup):
    user, _, project = issue_setup
    project.is_enabled = False
    project.save(update_fields=["is_enabled"])
    client.force_login(user)

    response = client.get(reverse("jira_integration:issue", args=["DEMO-1"]))

    assert response.status_code == 404


@pytest.mark.parametrize(
    ("role", "active", "expected_status"),
    [
        (ModuleUser.Role.INTERN, False, 403),
        (ModuleUser.Role.STAFF, True, 200),
    ],
)
def test_issue_page_checks_profile(
    client, issue_setup, role, active, expected_status
):
    user, profile, _ = issue_setup
    profile.role = role
    profile.is_active = active
    profile.save(update_fields=["role", "is_active"])
    client.force_login(user)

    response = client.get(reverse("jira_integration:issue", args=["DEMO-1"]))

    assert response.status_code == expected_status
    assert 'id="jira-issue"' not in response.content.decode()