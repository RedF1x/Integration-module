import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.urls import reverse
from django.utils import timezone

from jira_integration.models import (
    JiraIssue,
    JiraProject,
    JiraStatus,
    JiraUser,
    ModuleUser,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def profile(django_user_model):
    user = django_user_model.objects.create_user(username="owner-intern")
    return ModuleUser.objects.create(
        user=user,
        role=ModuleUser.Role.INTERN,
        is_active=True,
    )


def link_profile():
    call_command(
        "link_jira_user",
        "owner-intern",
        "--account-id",
        "jira-101",
        "--owner-from-assignee",
    )


@pytest.mark.parametrize("already_linked", [False, True])
@pytest.mark.parametrize("empty_owner", [None, "", "   "])
def test_fills_empty_owner_and_can_be_repeated(
    profile, already_linked, empty_owner
):
    jira_user = JiraUser.objects.create(
        account_id="jira-101",
        display_name="Intern",
    )
    profile.owner_ref = empty_owner
    if already_linked:
        profile.jira_user = jira_user
    profile.save()

    for _ in range(2):
        link_profile()
        profile.refresh_from_db()

        assert profile.jira_user == jira_user
        assert profile.owner_ref == "jira-101"


@pytest.mark.parametrize("already_linked", [False, True])
def test_conflicting_owner_leaves_profile_unchanged(profile, already_linked):
    jira_user = JiraUser.objects.create(
        account_id="jira-101",
        display_name="Intern",
    )
    profile.owner_ref = "another-owner"
    if already_linked:
        profile.jira_user = jira_user
    profile.save()
    previous_jira_user_id = profile.jira_user_id

    with pytest.raises(CommandError, match="owner_ref"):
        link_profile()

    profile.refresh_from_db()
    assert profile.owner_ref == "another-owner"
    assert profile.jira_user_id == previous_jira_user_id


def test_link_without_flag_preserves_owner(profile):
    jira_user = JiraUser.objects.create(
        account_id="jira-101",
        display_name="Intern",
    )
    profile.owner_ref = "custom-owner"
    profile.save(update_fields=["owner_ref"])

    call_command(
        "link_jira_user",
        "owner-intern",
        "--account-id",
        "jira-101",
    )

    profile.refresh_from_db()
    assert profile.jira_user == jira_user
    assert profile.owner_ref == "custom-owner"


def test_link_makes_only_own_issues_visible_in_api(client, profile):
    jira_user = JiraUser.objects.create(
        account_id="jira-101",
        display_name="Intern",
    )
    project = JiraProject.objects.create(
        jira_id="1",
        project_key="DEMO",
        name="Demo",
        is_enabled=True,
    )
    status = JiraStatus.objects.create(
        jira_id="1",
        name="К выполнению",
        category="todo",
    )
    now = timezone.now()

    for key, owner in [
        ("DEMO-1", "jira-101"),
        ("DEMO-2", "jira-102"),
    ]:
        JiraIssue.objects.create(
            jira_id=key,
            issue_key=key,
            project=project,
            status=status,
            summary=key,
            issue_type="Task",
            owner_ref=owner,
            assignee=jira_user if owner == "jira-101" else None,
            updated_jira=now,
            synced_at=now,
        )

    client.force_login(profile.user)
    backlog_url = reverse("jira_integration:api_backlog")
    own_url = reverse("jira_integration:api_issue", args=["DEMO-1"])
    foreign_url = reverse("jira_integration:api_issue", args=["DEMO-2"])

    before = client.get(backlog_url)
    assert before.status_code == 200
    assert before.json()["count"] == 0
    assert client.get(own_url).status_code == 404

    link_profile()

    after = client.get(backlog_url)
    assert after.status_code == 200
    assert after.json()["count"] == 1
    assert [item["key"] for item in after.json()["results"]] == ["DEMO-1"]
    assert client.get(own_url).status_code == 200
    assert client.get(foreign_url).status_code == 404