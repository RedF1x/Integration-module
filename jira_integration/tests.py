import pytest
from django.urls import reverse

from .models import ModuleUser


def test_anonymous_index_redirects_to_login(client):
    index = reverse("jira_integration:index")
    login = reverse("jira_integration:login")

    response = client.get(index)

    assert response.status_code == 302
    assert response.url == f"{login}?next={index}"


@pytest.mark.django_db
def test_login_and_logout(client, django_user_model):
    user = django_user_model.objects.create_user(
        username="test-intern",
        password="test-only-password",
    )
    ModuleUser.objects.create(
        user=user,
        role=ModuleUser.Role.INTERN,
        is_active=True,
    )
    index = reverse("jira_integration:index")
    login = reverse("jira_integration:login")
    logout = reverse("jira_integration:logout")

    assert client.get(login).status_code == 200

    response = client.post(
        login,
        {"username": "test-intern", "password": "test-only-password", "next": index},
    )
    assert response.status_code == 302
    assert response.url == index
    page = client.get(index)
    assert page.status_code == 200
    assert "Модуль интеграции Jira запущен." in page.content.decode()

    assert client.get(logout).status_code == 405
    response = client.post(logout)
    assert response.status_code == 302
    assert response.url == login
    assert client.get(index).url == f"{login}?next={index}"


@pytest.mark.django_db
@pytest.mark.parametrize("has_profile", [False, True], ids=["no-profile", "inactive-profile"])
def test_index_denies_user_without_active_profile(client, django_user_model, has_profile):
    user = django_user_model.objects.create_user(username="blocked-user")
    if has_profile:
        ModuleUser.objects.create(
            user=user,
            role=ModuleUser.Role.INTERN,
            is_active=False,
        )
    client.force_login(user)

    response = client.get(reverse("jira_integration:index"))

    assert response.status_code == 403


@pytest.mark.django_db
def test_staff_sees_jira_link_instead_of_intern_page(client, django_user_model, settings):
    settings.JIRA_BASE_URL = "https://jira.example.test"
    user = django_user_model.objects.create_user(username="employee")
    ModuleUser.objects.create(user=user, role=ModuleUser.Role.STAFF, is_active=True)
    client.force_login(user)

    response = client.get(reverse("jira_integration:index"))

    assert response.status_code == 200
    html = response.content.decode()
    assert 'href="https://jira.example.test"' in html
    assert "Модуль интеграции Jira запущен." not in html