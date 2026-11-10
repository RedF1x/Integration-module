import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ImproperlyConfigured

from jira_integration.identity import get_identity_provider
from jira_integration.identity.local import LocalIdentity
from jira_integration.models import ModuleUser

pytestmark = pytest.mark.django_db


def test_anonymous_user_has_no_profile():
    assert LocalIdentity().get_profile(AnonymousUser()) is None


def test_user_without_module_profile(django_user_model):
    user = django_user_model.objects.create_user(username="no-profile")

    assert LocalIdentity().get_profile(user) is None


@pytest.mark.parametrize("role", [ModuleUser.Role.INTERN, ModuleUser.Role.STAFF])
def test_returns_users_own_active_profile(django_user_model, role):
    other = django_user_model.objects.create_user(username="other")
    ModuleUser.objects.create(user=other, role=role, is_active=True)

    user = django_user_model.objects.create_user(username="target")
    profile = ModuleUser.objects.create(user=user, role=role, is_active=True)

    result = LocalIdentity().get_profile(user)

    assert result == profile
    assert result.role == role


@pytest.mark.parametrize("user_active, profile_active", [(False, True), (True, False)])
def test_disabled_user_or_profile_has_no_access(
    django_user_model, user_active, profile_active
):
    user = django_user_model.objects.create_user(
        username="disabled", is_active=user_active
    )
    ModuleUser.objects.create(
        user=user, role=ModuleUser.Role.INTERN, is_active=profile_active
    )

    assert LocalIdentity().get_profile(user) is None

def test_local_setting_selects_local_identity(settings):
    settings.JIRA_IDENTITY = "local"

    assert isinstance(get_identity_provider(), LocalIdentity)


def test_unknown_identity_setting_is_rejected(settings):
    settings.JIRA_IDENTITY = "locla"

    with pytest.raises(ImproperlyConfigured, match="JIRA_IDENTITY"):
        get_identity_provider()