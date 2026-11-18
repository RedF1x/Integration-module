from django.db import transaction
from django.utils import timezone

from jira_integration.models import (
    JiraComment,
    JiraFieldDef,
    JiraIssue,
    JiraProject,
    JiraStatus,
    JiraSyncRun,
)
from jira_integration.policy.rules import Field, Policy, Rule

from .django_store import DjangoStore, _upsert_sprint
from .locking import sync_lock


class RealStore(DjangoStore):
    """Записывает только DTO, уже прошедшие политику."""

    def __init__(self, kind):
        self.kind = kind

    def lock(self):
        return sync_lock()

    def last_success(self):
        return (
            JiraSyncRun.objects.filter(
                source=self.kind,
                status="success",
            )
            .order_by("-started_at", "-pk")
            .first()
        )

    @transaction.atomic
    def start_run(self, mode):
        # Вызывается под общей блокировкой: running от прежнего процесса уже
        # не может быть живым запуском этого сервиса.
        JiraSyncRun.objects.filter(status="running").update(
            status="failed",
            finished_at=timezone.now(),
            error_code="interrupted",
            error_message="Предыдущий процесс завершился без результата",
        )
        return JiraSyncRun.objects.create(source=self.kind, mode=mode).pk

    def finish_run(self, run_id, result):
        super().finish_run(run_id, result)
        JiraSyncRun.objects.filter(pk=run_id).update(deleted_count=result.deleted)

    def policy(self):
        project = JiraProject.objects.filter(project_key="SCRUM").first()
        if project is None or not project.is_enabled:
            return Policy(False)
        fields = tuple(
            Field(f.jira_field_id, f.purpose, f.value_type)
            for f in JiraFieldDef.objects.filter(is_enabled=True)
        )
        rules = tuple(
            Rule(
                r.source,
                r.expected_value,
                r.field_def.jira_field_id if r.field_def else None,
            )
            for r in project.visibility_rules.filter(is_enabled=True).select_related(
                "field_def"
            )
        )
        return Policy(True, fields, rules)

    @transaction.atomic
    def refresh_catalog(self, catalog):
        self.upsert_project(catalog.project)
        project = JiraProject.objects.get(project_key="SCRUM")
        for status in catalog.statuses.values():
            JiraStatus.objects.update_or_create(
                jira_id=status.jira_id,
                defaults={
                    "name": status.name,
                    "category": status.category,
                    "position": catalog.positions.get(status.jira_id, 10000),
                },
            )
        for sprint in catalog.sprints.values():
            _upsert_sprint(sprint, project)

    @transaction.atomic
    def apply_local_restrictions(self, policy, config):
        issues = JiraIssue.objects.filter(project__project_key="SCRUM")
        if not policy.enabled or not policy.rules:
            count = issues.count()
            issues.delete()
            return count
        if not config.descriptions:
            issues.update(description_html=None)
        if not config.comments:
            JiraComment.objects.filter(issue__in=issues).delete()
        permitted = {f.jira_id for f in policy.fields if f.purpose == "display"}
        for issue in issues.only("pk", "custom_fields").iterator():
            cleaned = {k: v for k, v in issue.custom_fields.items() if k in permitted}
            if cleaned != issue.custom_fields:
                issues.filter(pk=issue.pk).update(custom_fields=cleaned)
        return 0

    def stored_keys(self):
        return list(
            JiraIssue.objects.filter(project__project_key="SCRUM").values_list(
                "jira_id", "issue_key"
            )
        )

    def close_previous_owner(self, decision):
        # Отзыв переживает ошибку последующего разбора или записи задачи.
        JiraIssue.objects.filter(
            jira_id=decision.jira_id, project__project_key="SCRUM"
        ).exclude(owner_ref=decision.owner_ref).update(owner_ref=None)

    @transaction.atomic
    def upsert_allowed(self, dto, decision, catalog, raw):
        if not decision.allowed or not decision.owner_ref:
            raise ValueError("Запись запрещена политикой")
        if (
            decision.jira_id != dto.jira_id
            or dto.assignee is None
            or dto.assignee.account_id != decision.owner_ref
        ):
            raise ValueError("Результат политики не соответствует DTO")
        created = super().upsert_issue(dto)
        priority = raw["fields"]["priority"]
        order = catalog.priorities.get(str(priority["id"])) if priority else None
        JiraIssue.objects.filter(jira_id=dto.jira_id).update(
            owner_ref=decision.owner_ref,
            priority_order=order,
        )
        JiraStatus.objects.filter(jira_id=dto.status.jira_id).update(
            position=catalog.positions.get(dto.status.jira_id, 10000),
        )
        return created

    def revoke(self, identity):
        issues = JiraIssue.objects.filter(
            jira_id=identity, project__project_key="SCRUM"
        )
        count = issues.count()
        issues.delete()
        return count
