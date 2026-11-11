from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import transaction
from django.utils import timezone

from jira_integration.dto import IssueDTO, ProjectDTO, SprintDTO, UserDTO, parse_iso
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

if TYPE_CHECKING:
    from jira_integration.sync.service import SyncResult


def _upsert_user(dto: UserDTO | None) -> JiraUser | None:
    if dto is None:
        return None
    user, _ = JiraUser.objects.update_or_create(
        account_id=dto.account_id,
        defaults={
            "display_name": dto.display_name,
            "email": dto.email,
            "avatar_url": dto.avatar_url,
        },
    )
    return user


def _upsert_sprint(dto: SprintDTO | None, project: JiraProject) -> JiraSprint | None:
    if dto is None:
        return None
    values = {
        "name": dto.name,
        "state": dto.state,
        "start_date": parse_iso(dto.start_date) if dto.start_date is not None else None,
        "end_date": parse_iso(dto.end_date) if dto.end_date is not None else None,
    }
    sprint, _ = JiraSprint.objects.update_or_create(
        jira_id=dto.jira_id,
        defaults=values,
        create_defaults={**values, "project": project},
    )
    if sprint.project_id != project.pk:
        raise ValueError("Спринт уже связан с другим проектом.")
    return sprint


class DjangoStore:
    def upsert_project(self, project: ProjectDTO) -> None:
        JiraProject.objects.update_or_create(
            jira_id=project.jira_id,
            defaults={"project_key": project.key, "name": project.name},
        )

    @transaction.atomic
    def upsert_issue(self, dto: IssueDTO) -> bool:
        project = JiraProject.objects.get(project_key=dto.project_key)
        status, _ = JiraStatus.objects.update_or_create(
            jira_id=dto.status.jira_id,
            defaults={"name": dto.status.name, "category": dto.status.category},
        )
        issue, created = JiraIssue.objects.update_or_create(
            jira_id=dto.jira_id,
            defaults={
                "issue_key": dto.key,
                "project": project,
                "status": status,
                "assignee": _upsert_user(dto.assignee),
                "sprint": _upsert_sprint(dto.sprint, project),
                "summary": dto.summary,
                "issue_type": dto.issue_type,
                "priority": dto.priority,
                "description_html": dto.description_html,
                "labels": dto.labels,
                "custom_fields": dto.custom_fields,
                "rank": dto.rank,
                "updated_jira": parse_iso(dto.updated_at),
                "synced_at": timezone.now(),
                "owner_ref": None,
            },
        )
        self._save_comments(issue, dto)
        self._save_links(issue, dto)
        return created

    @staticmethod
    def _save_comments(issue: JiraIssue, dto: IssueDTO) -> None:
        kept_ids = []
        for comment in dto.comments:
            values = {
                "author": _upsert_user(comment.author),
                "body_html": comment.body_html,
                "created_jira": parse_iso(comment.created_at),
            }
            saved, _ = JiraComment.objects.update_or_create(
                jira_id=comment.jira_id,
                defaults=values,
                create_defaults={**values, "issue": issue},
            )
            if saved.issue_id != issue.pk:
                raise ValueError("Комментарий уже связан с другой задачей.")
            kept_ids.append(saved.pk)
        # В mock-файле комментарии и связи задачи представлены целиком.
        issue.comments.exclude(pk__in=kept_ids).delete()

    @staticmethod
    def _save_links(issue: JiraIssue, dto: IssueDTO) -> None:
        kept_ids = []
        for link in dto.links:
            saved, _ = JiraIssueLink.objects.get_or_create(
                from_issue=issue,
                to_key=link.target_key,
                link_type=link.link_type,
                direction=link.direction,
            )
            kept_ids.append(saved.pk)
        issue.links.exclude(pk__in=kept_ids).delete()

    def start_run(self, mode: str) -> int:
        return JiraSyncRun.objects.create(source=JiraSyncRun.Source.MOCK, mode=mode).pk

    def finish_run(self, run_id: int, result: SyncResult) -> None:
        JiraSyncRun.objects.filter(pk=run_id).update(
            status=result.status,
            finished_at=timezone.now(),
            created_count=result.created,
            updated_count=result.updated,
            failed_count=result.failed,
            error_code="sync_failed" if result.failed else None,
            error_message="; ".join(result.errors) or None,
        )
