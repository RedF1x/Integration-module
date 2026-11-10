import json

import pytest
from django.contrib.auth.models import AnonymousUser
from django.http import JsonResponse

from jira_integration.decorators import intern_api_required, staff_required
from jira_integration.models import ModuleUser


def endpoint(request):
    return JsonResponse({"ok": True})


@pytest.mark.parametrize("guard", [intern_api_required, staff_required])
def test_anonymous_api_request_returns_401(rf, guard):
    request = rf.get("/jira/api/test/")
    request.user = AnonymousUser()

    response = guard(endpoint)(request)

    assert response.status_code == 401
    assert json.loads(response.content)["error"] == "unauthorized"


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("guard", "role", "active", "expected_status"),
    [
        (intern_api_required, ModuleUser.Role.INTERN, True, 200),
        (intern_api_required, ModuleUser.Role.STAFF, True, 403),
        (staff_required, ModuleUser.Role.STAFF, True, 200),
        (staff_required, ModuleUser.Role.INTERN, True, 403),
        (staff_required, ModuleUser.Role.STAFF, False, 403),
        (staff_required, None, False, 403),
    ],
)
def test_api_role_access(rf, django_user_model, guard, role, active, expected_status):
    user = django_user_model.objects.create_user(username="api-user")
    if role is not None:
        ModuleUser.objects.create(user=user, role=role, is_active=active)

    request = rf.get("/jira/api/test/")
    request.user = user

    response = guard(endpoint)(request)

    assert response.status_code == expected_status
    body = json.loads(response.content)
    if expected_status == 200:
        assert body == {"ok": True}
    else:
        assert body["error"] == "forbidden"
        assert body["message"]