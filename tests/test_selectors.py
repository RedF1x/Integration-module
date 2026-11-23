from datetime import timedelta

import pytest
from django.http import Http404
from django.utils import timezone

from jira_integration.models import (
    JiraIssue,
    JiraIssueLink,
    JiraProject,
    JiraSprint,
    JiraStatus,
    JiraUser,
    ModuleUser,
)
from jira_integration.selectors import (
    get_backlog,
    get_backlog_filter_options,
    get_board,
    get_issue,
    visible_issues_for,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def intern(django_user_model):
    user = django_user_model.objects.create_user(username="intern")
    return ModuleUser.objects.create(
        user=user,
        role=ModuleUser.Role.INTERN,
        is_active=True,
        owner_ref="intern-1",
    )


@pytest.fixture
def make_issue():
    status = JiraStatus.objects.create(jira_id="1", name="К выполнению", category="todo")
    now = timezone.now()

    def create(key, project, owner_ref, *, sprint=None, rank=None, issue_status=None):
        return JiraIssue.objects.create(
            jira_id=key,
            issue_key=key,
            project=project,
            status=issue_status or status,
            sprint=sprint,
            rank=rank,
            summary=key,
            issue_type="Task",
            owner_ref=owner_ref,
            updated_jira=now,
            synced_at=now,
        )

    return create


def test_intern_sees_only_own_issues_in_enabled_projects(intern, make_issue):
    enabled = JiraProject.objects.create(
        jira_id="1", project_key="DEMO", name="Демо", is_enabled=True
    )
    disabled = JiraProject.objects.create(
        jira_id="2", project_key="OLD", name="Архив", is_enabled=False
    )
    own = make_issue("DEMO-1", enabled, "intern-1")
    make_issue("DEMO-2", enabled, "intern-2")
    make_issue("OLD-1", disabled, "intern-1")

    assert list(visible_issues_for(intern.user)) == [own]


@pytest.mark.parametrize("empty_ref", [None, "", "   "])
def test_empty_owner_cannot_see_unassigned_issue(intern, make_issue, empty_ref):
    intern.owner_ref = empty_ref
    intern.save(update_fields=["owner_ref"])
    project = JiraProject.objects.create(
        jira_id="1", project_key="DEMO", name="Демо", is_enabled=True
    )
    make_issue("DEMO-1", project, empty_ref)

    assert not visible_issues_for(intern.user).exists()

def test_get_issue_returns_only_links_to_visible_targets(intern, make_issue):
    project = JiraProject.objects.create(
        jira_id="1", project_key="DEMO", name="Демо", is_enabled=True
    )
    own = make_issue("DEMO-1", project, "intern-1")
    visible_target = make_issue("DEMO-2", project, "intern-1")
    hidden_target = make_issue("DEMO-3", project, "intern-2")

    for target in (visible_target, hidden_target):
        JiraIssueLink.objects.create(
            from_issue=own,
            to_key=target.issue_key,
            link_type="Relates",
            direction="outward",
        )

    result = get_issue(intern.user, own.issue_key)

    assert result.pk == own.pk
    assert [link.to_key for link in result.visible_links] == ["DEMO-2"]


@pytest.mark.parametrize("key", ["DEMO-2", "DEMO-999"])
def test_get_issue_returns_404_for_foreign_or_missing_key(intern, make_issue, key):
    project = JiraProject.objects.create(
        jira_id="1", project_key="DEMO", name="Демо", is_enabled=True
    )
    make_issue("DEMO-2", project, "intern-2")

    with pytest.raises(Http404):
        get_issue(intern.user, key)



def test_board_groups_and_orders_only_visible_active_issues(intern, make_issue):
    project = JiraProject.objects.create(
        jira_id="1", project_key="DEMO", name="Демо", is_enabled=True
    )
    sprint = JiraSprint.objects.create(
        jira_id="10", project=project, name="Спринт 1", state=JiraSprint.State.ACTIVE
    )
    done = JiraStatus.objects.create(
        jira_id="2", name="Готово", category=JiraStatus.Category.DONE
    )

    make_issue("DEMO-1", project, "intern-1", sprint=sprint, rank="b")
    make_issue("DEMO-2", project, "intern-1", sprint=sprint, rank="a")
    make_issue("DEMO-3", project, "intern-1", sprint=sprint, issue_status=done)
    make_issue("DEMO-4", project, "intern-2", sprint=sprint)
    make_issue("DEMO-5", project, "intern-1")

    board = get_board(intern.user, project_key="DEMO")

    assert board["sprint"] == sprint
    assert [
        (column["category"], [issue.issue_key for issue in column["issues"]])
        for column in board["columns"]
    ] == [
        ("todo", ["DEMO-2", "DEMO-1"]),
        ("done", ["DEMO-3"]),
    ]


def test_board_hides_sprint_with_only_foreign_issues(intern, make_issue):
    project = JiraProject.objects.create(
        jira_id="1", project_key="DEMO", name="Демо", is_enabled=True
    )
    sprint = JiraSprint.objects.create(
        jira_id="10", project=project, name="Спринт 1", state=JiraSprint.State.ACTIVE
    )
    make_issue("DEMO-1", project, "intern-2", sprint=sprint)

    assert get_board(intern.user) == {"sprint": None, "columns": [], "synced_at": None}


def test_backlog_excludes_active_and_foreign_issues(intern, make_issue):
    project = JiraProject.objects.create(
        jira_id="1", project_key="DEMO", name="Демо", is_enabled=True
    )
    for state in (JiraSprint.State.ACTIVE, JiraSprint.State.FUTURE, JiraSprint.State.CLOSED):
        sprint = JiraSprint.objects.create(
            jira_id=state, project=project, name=state, state=state
        )
        make_issue(f"DEMO-{state}", project, "intern-1", sprint=sprint)

    make_issue("DEMO-own", project, "intern-1")
    make_issue("DEMO-other", project, "intern-2")

    backlog = get_backlog(intern.user, sort="key")

    assert backlog["count"] == 3
    assert [issue.issue_key for issue in backlog["results"]] == [
        "DEMO-closed",
        "DEMO-future",
        "DEMO-own",
    ]


def test_backlog_filters_before_counting_and_paging(intern, make_issue):
    project = JiraProject.objects.create(
        jira_id="1", project_key="DEMO", name="Демо", is_enabled=True
    )
    make_issue("DEMO-1", project, "intern-1", rank="b")
    make_issue("DEMO-2", project, "intern-1", rank="a")
    bug = make_issue("DEMO-3", project, "intern-1", rank="0")
    bug.issue_type = "Bug"
    bug.save(update_fields=["issue_type"])

    first = get_backlog(intern.user, filters={"type": "Task"}, page=1, page_size=1)
    second = get_backlog(intern.user, filters={"type": "Task"}, page=2, page_size=1)

    assert first["count"] == second["count"] == 2
    assert [issue.issue_key for issue in first["results"]] == ["DEMO-2"]
    assert [issue.issue_key for issue in second["results"]] == ["DEMO-1"]
    assert first["synced_at"] == second["synced_at"]


@pytest.fixture
def backlog_with_details(intern, make_issue):
    project = JiraProject.objects.create(
        jira_id="1", project_key="DEMO", name="Демо", is_enabled=True
    )
    alex = JiraUser.objects.create(account_id="acc-alex", display_name="Алексей")
    done = JiraStatus.objects.create(jira_id="2", name="Готово", category="done")
    now = timezone.now()

    # Ключ, исполнитель, статус, время обновления, порядок приоритета.
    rows = [
        ("DEMO-1", alex, None, now, 2),
        ("DEMO-2", alex, done, now - timedelta(days=2), 1),
        ("DEMO-3", None, done, now - timedelta(days=1), None),
    ]
    for key, assignee, status, updated, priority in rows:
        issue = make_issue(key, project, intern.owner_ref, issue_status=status)
        JiraIssue.objects.filter(pk=issue.pk).update(
            assignee=assignee, updated_jira=updated, priority_order=priority
        )

    return intern.user


@pytest.mark.parametrize(
    ("filters", "expected_keys"),
    [
        ({"assignee": "acc-alex"}, ["DEMO-1", "DEMO-2"]),
        ({"status": "2"}, ["DEMO-2", "DEMO-3"]),
        ({"assignee": "acc-alex", "status": "2"}, ["DEMO-2"]),
    ],
)
def test_backlog_filters_by_assignee_and_status(backlog_with_details, filters, expected_keys):
    result = get_backlog(backlog_with_details, filters=filters, sort="key")

    assert result["count"] == len(expected_keys)
    assert [issue.issue_key for issue in result["results"]] == expected_keys


@pytest.mark.parametrize(
    ("sort", "expected_keys"),
    [
        ("updated", ["DEMO-1", "DEMO-3", "DEMO-2"]),
        ("priority", ["DEMO-2", "DEMO-1", "DEMO-3"]),
    ],
)
def test_backlog_sort_order(backlog_with_details, sort, expected_keys):
    result = get_backlog(backlog_with_details, sort=sort)

    assert [issue.issue_key for issue in result["results"]] == expected_keys


def test_backlog_loads_card_details_without_extra_queries(
    backlog_with_details, django_assert_num_queries
):
    with django_assert_num_queries(4):
        result = get_backlog(backlog_with_details, sort="key")
        cards = [
            (issue.status.name, issue.assignee.display_name if issue.assignee else None)
            for issue in result["results"]
        ]

    assert cards == [
        ("К выполнению", "Алексей"),
        ("Готово", "Алексей"),
        ("Готово", None),
    ]


@pytest.mark.parametrize("hidden_reason", ["foreign", "disabled", "active"])
def test_backlog_filter_options_include_only_visible_backlog(
    intern, make_issue, client, hidden_reason
):
    project = JiraProject.objects.create(
        jira_id="1", project_key="DEMO", name="Demo", is_enabled=True
    )
    own_assignee = JiraUser.objects.create(
        account_id="own-account", display_name="Доступный исполнитель"
    )

    for key in ("DEMO-1", "DEMO-2"):
        issue = make_issue(key, project, intern.owner_ref)
        issue.assignee = own_assignee
        issue.save(update_fields=["assignee"])

    hidden_project = project
    hidden_owner = intern.owner_ref
    hidden_sprint = None

    if hidden_reason == "foreign":
        hidden_owner = "another-owner"
    elif hidden_reason == "disabled":
        hidden_project = JiraProject.objects.create(
            jira_id="2", project_key="OLD", name="Old", is_enabled=False
        )
    else:
        hidden_sprint = JiraSprint.objects.create(
            jira_id="10",
            project=project,
            name="Active",
            state=JiraSprint.State.ACTIVE,
        )

    hidden_status = JiraStatus.objects.create(
        jira_id="hidden-status",
        name="Скрытый статус",
        category="todo",
    )
    hidden_assignee = JiraUser.objects.create(
        account_id="hidden-account", display_name="Скрытый исполнитель"
    )
    hidden_issue = make_issue(
        "HIDDEN-1",
        hidden_project,
        hidden_owner,
        sprint=hidden_sprint,
        issue_status=hidden_status,
    )
    hidden_issue.assignee = hidden_assignee
    hidden_issue.issue_type = "HiddenType"
    hidden_issue.save(update_fields=["assignee", "issue_type"])

    options = get_backlog_filter_options(intern.user)

    assert options == {
        "statuses": [("1", "К выполнению")],
        "types": ["Task"],
        "assignees": [("own-account", "Доступный исполнитель")],
    }

    client.force_login(intern.user)
    response = client.get("/jira/backlog/")

    assert response.status_code == 200
    assert response.context["filter_options"] == options
    html = response.content.decode()
    assert "Скрытый статус" not in html
    assert "Скрытый исполнитель" not in html
    assert "HiddenType" not in html