import pytest

from jira_integration.models import JiraIssue, JiraStatus, JiraUser
from jira_integration.serializers import serialize_card


@pytest.mark.parametrize("has_assignee", [True, False])
def test_card_contains_only_contract_fields(has_assignee):
    status = JiraStatus(jira_id="10", name="В работе", category="in_progress")
    assignee = None
    expected_assignee = None

    if has_assignee:
        assignee = JiraUser(
            account_id="internal-account-id",
            display_name="Анна",
            email="anna@example.test",
            avatar_url="https://example.test/avatar.png",
        )
        expected_assignee = {
            "display_name": "Анна",
            "avatar_url": "https://example.test/avatar.png",
        }

    issue = JiraIssue(
        jira_id="10001",
        issue_key="DEMO-1",
        summary="Подготовить страницу",
        status=status,
        issue_type="Task",
        priority=None,
        assignee=assignee,
        owner_ref="internal-owner",
        description_html="<p>Описание задачи</p>",
        custom_fields={"internal_field": "internal-value"},
    )

    assert serialize_card(issue) == {
        "key": "DEMO-1",
        "summary": "Подготовить страницу",
        "status": "В работе",
        "issue_type": "Task",
        "priority": None,
        "assignee": expected_assignee,
    }