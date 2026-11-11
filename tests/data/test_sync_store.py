from dataclasses import replace
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from jira_integration.dto import UserDTO, parse_iso
from jira_integration.models import (
    JiraComment,
    JiraIssue,
    JiraIssueLink,
    JiraProject,
    JiraSprint,
    JiraStatus,
    JiraSyncRun,
    JiraUser,
)
from jira_integration.sources import FileSource
from jira_integration.sync.django_store import DjangoStore
from jira_integration.sync.service import run_sync

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "dto"


@pytest.fixture
def source(monkeypatch):
    monkeypatch.setenv("JIRA_SOURCE", "mock")
    monkeypatch.setenv("JIRA_MOCK_DIR", str(FIXTURES))
    return FileSource(FIXTURES)


@pytest.mark.django_db
def test_full_command_loads_sample_twice_without_duplicates(source):
    call_command("sync_jira", "--full", stdout=StringIO())
    models = (
        JiraProject,
        JiraStatus,
        JiraUser,
        JiraSprint,
        JiraIssue,
        JiraComment,
        JiraIssueLink,
    )
    before = [
        list(model.objects.order_by("pk").values_list("pk", flat=True))
        for model in models
    ]
    call_command("sync_jira", "--full", stdout=StringIO())

    assert [
        list(model.objects.order_by("pk").values_list("pk", flat=True))
        for model in models
    ] == before
    project = JiraProject.objects.get(project_key="DEMO")
    assert project.jira_id == "10100" and project.is_enabled is False
    issue = JiraIssue.objects.get(issue_key="DEMO-1")
    dto = source.issue_detail("DEMO-1")
    assert issue.assignee.account_id == dto.assignee.account_id
    assert issue.sprint.jira_id == dto.sprint.jira_id
    assert issue.updated_jira == parse_iso(dto.updated_at)
    assert issue.comments.get().jira_id == dto.comments[0].jira_id
    assert issue.links.get().to_key == dto.links[0].target_key
    assert issue.owner_ref is None
    assert JiraIssue.objects.count() == 4
    runs = list(JiraSyncRun.objects.order_by("pk"))
    assert [(run.created_count, run.updated_count) for run in runs] == [(4, 0), (0, 4)]
    assert all(
        run.status == "success"
        and run.source == "mock"
        and run.mode == "full"
        and run.finished_at >= run.started_at
        for run in runs
    )


@pytest.mark.django_db
def test_reimport_updates_fields_and_keeps_local_configuration(source):
    run_sync(source)
    JiraProject.objects.update(is_enabled=True)
    JiraStatus.objects.update(position=7)
    issue = JiraIssue.objects.get(issue_key="DEMO-1")
    issue.priority_order = 3
    issue.owner_ref = "previous-owner"
    issue.save(update_fields=["priority_order", "owner_ref"])
    dto = source.issue_detail("DEMO-1")
    changed = replace(
        dto,
        summary="Обновлённая задача",
        assignee=None,
        sprint=None,
        labels=[],
        comments=[],
        links=[],
        updated_at="2026-11-11T12:00:00Z",
    )
    store = DjangoStore()
    store.upsert_project(source.projects()[0])
    assert store.upsert_issue(changed) is False

    issue.refresh_from_db()
    assert issue.summary == "Обновлённая задача"
    assert issue.updated_jira == parse_iso(changed.updated_at)
    assert (
        issue.assignee_id is None
        and issue.sprint_id is None
        and issue.owner_ref is None
    )
    assert (
        issue.labels == [] and not issue.comments.exists() and not issue.links.exists()
    )
    assert (
        issue.project.is_enabled
        and issue.status.position == 7
        and issue.priority_order == 3
    )


@pytest.mark.django_db
def test_assignee_with_hidden_email_is_saved_by_account_id(source):
    dto = source.issue_detail("DEMO-1")
    store = DjangoStore()
    store.upsert_project(source.projects()[0])
    store.upsert_issue(dto)
    store.upsert_issue(replace(dto, assignee=replace(dto.assignee, email=None)))

    user = JiraUser.objects.get(account_id=dto.assignee.account_id)
    assert user.email is None


@pytest.mark.django_db(transaction=True)
def test_failed_issue_rolls_back_and_run_keeps_other_tasks(source, monkeypatch):
    first, second, third, fourth = list(source.issues())
    invalid = replace(
        second,
        key=first.key,
        assignee=UserDTO(account_id="rolled-back-account", display_name="Test"),
    )
    monkeypatch.setattr(source, "issues", lambda: iter([first, invalid, third, fourth]))
    result = run_sync(source)

    assert (result.created, result.failed) == (3, 1)
    assert not JiraUser.objects.filter(account_id="rolled-back-account").exists()
    assert not JiraIssue.objects.filter(jira_id=second.jira_id).exists()
    assert JiraIssue.objects.filter(jira_id=fourth.jira_id).exists()
    run = JiraSyncRun.objects.get()
    assert run.status == "failed" and run.failed_count == 1 and run.created_count == 3
    assert run.error_message == f"{first.key}: IntegrityError"


@pytest.mark.django_db
def test_comment_id_collision_rolls_back_the_new_issue(source, monkeypatch):
    first, second = list(source.issues())[:2]
    invalid = replace(
        second, comments=[replace(first.comments[0], body_html="Wrong issue")]
    )
    monkeypatch.setattr(source, "issues", lambda: iter([first, invalid]))

    result = run_sync(source)

    assert (result.created, result.failed) == (1, 1)
    assert JiraIssue.objects.count() == 1
    comment = JiraComment.objects.get()
    assert (
        comment.issue.jira_id == first.jira_id
        and comment.body_html == first.comments[0].body_html
    )


def test_cli_dry_run_works_without_database(source):
    output = StringIO()
    call_command("sync_jira", "--full", "--dry-run", stdout=output)
    assert (
        "dry-run success: обработано 4, создано 0, обновлено 0, ошибок 0"
        in output.getvalue()
    )


def test_cli_reports_unavailable_source(monkeypatch):
    monkeypatch.setenv("JIRA_SOURCE", "rest")
    with pytest.raises(CommandError, match="RestSource"):
        call_command("sync_jira", "--full")
