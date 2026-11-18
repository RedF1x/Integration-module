from datetime import datetime, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from jira_integration.models import JiraSyncRun, ModuleUser

pytestmark = pytest.mark.django_db


@pytest.fixture
def intern_user(django_user_model):
    user = django_user_model.objects.create_user(username="status-intern")
    ModuleUser.objects.create(
        user=user,
        role=ModuleUser.Role.INTERN,
        is_active=True,
    )
    return user


def test_status_without_sync_runs(client, intern_user):
    client.force_login(intern_user)

    response = client.get(reverse("jira_integration:api_status"))

    assert response.status_code == 200
    assert response.json() == {
        "status": None,
        "started_at": None,
        "finished_at": None,
        "synced_at": None,
    }


def test_status_reports_latest_failure_and_previous_success(client, intern_user):
    now = timezone.now().replace(microsecond=0)
    success_finished = now - timedelta(hours=1)
    failed_started = now - timedelta(minutes=1)

    JiraSyncRun.objects.create(
        source="mock",
        mode="full",
        status="success",
        started_at=now - timedelta(hours=2),
        finished_at=success_finished,
    )
    JiraSyncRun.objects.create(
        source="mock",
        mode="incremental",
        status="failed",
        started_at=failed_started,
        finished_at=now,
        error_message="Internal diagnostic detail",
        error_code="internal_error",
        failed_count=5,
    )
    client.force_login(intern_user)

    response = client.get(reverse("jira_integration:api_status"))

    assert response.status_code == 200
    data = response.json()
    assert set(data) == {"status", "started_at", "finished_at", "synced_at"}
    assert data["status"] == "failed"
    assert datetime.fromisoformat(data["started_at"]) == failed_started
    assert datetime.fromisoformat(data["finished_at"]) == now
    assert datetime.fromisoformat(data["synced_at"]) == success_finished
    assert "Internal diagnostic detail" not in response.content.decode()


@pytest.mark.parametrize(
    ("role", "expected_status", "error"),
    [
        (None, 401, "unauthorized"),
        (ModuleUser.Role.STAFF, 403, "forbidden"),
    ],
)
def test_status_checks_access(client, intern_user, role, expected_status, error):
    if role is not None:
        ModuleUser.objects.filter(user=intern_user).update(role=role)
        client.force_login(intern_user)

    response = client.get(reverse("jira_integration:api_status"))

    assert response.status_code == expected_status
    assert response.json()["error"] == error