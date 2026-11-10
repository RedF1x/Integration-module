import pytest
from django.core.management import call_command

from jira_integration.models import ModuleUser


@pytest.mark.django_db
def test_seed_users_creates_profiles_and_preserves_password(django_user_model):
    call_command("seed_users")

    profiles = ModuleUser.objects.values_list("user__username", "role", "is_active")
    assert set(profiles) == {
        ("demo_intern_1", "intern", True),
        ("demo_intern_2", "intern", True),
        ("demo_staff", "staff", True),
    }

    intern = django_user_model.objects.get(username="demo_intern_1")
    assert not intern.has_usable_password()

    intern.set_password("only-for-this-test")
    intern.save(update_fields=["password"])

    call_command("seed_users")

    intern.refresh_from_db()
    assert intern.check_password("only-for-this-test")
    assert ModuleUser.objects.count() == 3