import pytest
from django.urls import reverse

from jira_integration.models import ModuleUser

pytestmark = pytest.mark.django_db


def test_anonymous_board_redirects_to_login(client):
    url = reverse("jira_integration:board")

    response = client.get(url)

    assert response.status_code == 302
    assert response.url == f"{reverse('jira_integration:login')}?next={url}"


@pytest.mark.parametrize(
    ("role", "active", "expected_status", "shows_board"),
    [
        (ModuleUser.Role.INTERN, True, 200, True),
        (ModuleUser.Role.INTERN, False, 403, False),
        (ModuleUser.Role.STAFF, True, 200, False),
        (None, False, 403, False),
    ],
)
def test_board_page_access(
    client, django_user_model, role, active, expected_status, shows_board
):
    user = django_user_model.objects.create_user(username="board-user")
    if role is not None:
        ModuleUser.objects.create(user=user, role=role, is_active=active)
    client.force_login(user)

    response = client.get(reverse("jira_integration:board"))

    assert response.status_code == expected_status
    html = response.content.decode()
    assert ('id="jira-board"' in html) is shows_board
    if shows_board:
        assert reverse("jira_integration:api_board") in html