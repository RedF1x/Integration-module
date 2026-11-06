from django.urls import reverse


def test_index_page(client):
    url = reverse("jira_integration:index")
    assert url == "/jira/"

    response = client.get(url)

    assert response.status_code == 200
    assert response.content.decode("utf-8") == "Модуль интеграции Jira запущен."