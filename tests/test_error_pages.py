import pytest
from django.urls import reverse
from django.utils import timezone

from jira_integration.models import JiraIssue, JiraProject, JiraStatus, ModuleUser

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def production_error_pages(settings):
    settings.DEBUG = False


def test_unknown_page_uses_jira_404_template(client):
    response = client.get("/jira/unknown-page/")

    assert response.status_code == 404
    assert "text/html" in response["Content-Type"]
    assert "jira_integration/404.html" in [
        template.name for template in response.templates
    ]
    assert "Страница не найдена" in response.content.decode()


def test_user_without_profile_sees_403_page(client, django_user_model):
    user = django_user_model.objects.create_user(username="without-profile")
    client.force_login(user)

    response = client.get(reverse("jira_integration:board"))

    assert response.status_code == 403
    assert "jira_integration/403.html" in [
        template.name for template in response.templates
    ]
    assert "Нет доступа" in response.content.decode()


def test_foreign_and_missing_issue_have_same_error_page(
    client, django_user_model
):
    user = django_user_model.objects.create_user(username="error-page-intern")
    ModuleUser.objects.create(
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
    JiraIssue.objects.create(
        jira_id="2",
        issue_key="DEMO-2",
        project=project,
        status=status,
        summary="Чужая задача, которую нельзя раскрывать",
        issue_type="Task",
        owner_ref="owner-2",
        updated_jira=now,
        synced_at=now,
    )
    client.force_login(user)

    for key in ("DEMO-2", "DEMO-999"):
        response = client.get(
            reverse("jira_integration:issue", args=[key])
        )

        assert response.status_code == 404
        assert "jira_integration/404.html" in [
            template.name for template in response.templates
        ]
        html = response.content.decode()
        assert "Страница не найдена" in html
        assert "Возможно, адрес указан неверно или задача недоступна." in html
        assert "Чужая задача, которую нельзя раскрывать" not in html
        assert key not in html


def test_non_jira_404_does_not_use_module_template(client):
    response = client.get("/unknown-outside-jira/")

    assert response.status_code == 404
    assert "jira_integration/404.html" not in [
        template.name for template in response.templates
    ]