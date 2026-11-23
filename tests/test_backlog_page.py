import pytest
from django.urls import reverse

from jira_integration.models import ModuleUser

pytestmark = pytest.mark.django_db


def test_anonymous_backlog_redirects_to_login(client):
    url = reverse("jira_integration:backlog")

    response = client.get(url)

    assert response.status_code == 302
    assert response.url == f"{reverse('jira_integration:login')}?next={url}"


@pytest.mark.parametrize(
    ("role", "active", "expected_status", "shows_backlog"),
    [
        (ModuleUser.Role.INTERN, True, 200, True),
        (ModuleUser.Role.INTERN, False, 403, False),
        (ModuleUser.Role.STAFF, True, 200, False),
        (None, False, 403, False),
    ],
)
def test_backlog_page_access(
    client, django_user_model, role, active, expected_status, shows_backlog
):
    user = django_user_model.objects.create_user(username="backlog-user")
    if role is not None:
        ModuleUser.objects.create(user=user, role=role, is_active=active)
    client.force_login(user)

    response = client.get(reverse("jira_integration:backlog"))

    assert response.status_code == expected_status
    html = response.content.decode()
    assert ('id="jira-backlog"' in html) is shows_backlog
    if shows_backlog:
        assert reverse("jira_integration:api_backlog") in html