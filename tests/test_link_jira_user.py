import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from jira_integration.models import JiraUser, ModuleUser

pytestmark = pytest.mark.django_db


@pytest.fixture
def profile(django_user_model):
    user = django_user_model.objects.create_user(
        username="intern",
        email="intern@example.test",
    )
    return ModuleUser.objects.create(
        user=user,
        role=ModuleUser.Role.INTERN,
        is_active=True,
    )


def test_links_by_account_id_when_jira_email_is_hidden(profile):
    jira_user = JiraUser.objects.create(account_id="jira-101", display_name="Intern")

    for _ in range(2):
        call_command("link_jira_user", "intern", "--account-id", "jira-101")

    profile.refresh_from_db()
    assert profile.jira_user == jira_user


def test_links_by_email_ignoring_case(profile):
    jira_user = JiraUser.objects.create(
        account_id="jira-102",
        display_name="Intern",
        email="INTERN@example.test",
    )

    call_command("link_jira_user", "intern", "--by-email")

    profile.refresh_from_db()
    assert profile.jira_user == jira_user


def test_ambiguous_email_leaves_profile_unlinked(profile):
    for account_id in ("jira-103", "jira-104"):
        JiraUser.objects.create(
            account_id=account_id,
            display_name="Intern",
            email="intern@example.test",
        )

    with pytest.raises(CommandError, match="несколько совпадений"):
        call_command("link_jira_user", "intern", "--by-email")

    profile.refresh_from_db()
    assert profile.jira_user_id is None