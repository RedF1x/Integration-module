import pytest
from django.urls import reverse

from jira_integration.models import ModuleUser


def test_unknown_api_url_returns_json(client, settings):
    settings.DEBUG = False

    response = client.get("/jira/api/unknown/")

    assert response.status_code == 404
    assert response.json() == {
        "error": "not_found",
        "message": "Адрес не найден.",
    }


@pytest.mark.django_db
def test_unexpected_api_error_returns_safe_json(
    client, settings, django_user_model, monkeypatch
):
    settings.DEBUG = False
    settings.DEBUG_PROPAGATE_EXCEPTIONS = False

    user = django_user_model.objects.create_user(username="error-test-intern")
    ModuleUser.objects.create(
        user=user,
        role=ModuleUser.Role.INTERN,
        is_active=True,
    )
    client.force_login(user)
    client.raise_request_exception = False

    def broken_backlog(*args, **kwargs):
        raise RuntimeError("Internal diagnostic detail")

    monkeypatch.setattr("jira_integration.api.get_backlog", broken_backlog)

    response = client.get(reverse("jira_integration:api_backlog"))

    assert response.status_code == 500
    assert response.json() == {
        "error": "server_error",
        "message": "Не удалось выполнить запрос.",
    }
    assert "Internal diagnostic detail" not in response.content.decode()