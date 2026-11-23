from django.core.paginator import Paginator
from django.db.models import Case, F, Max, Prefetch, When
from django.shortcuts import get_object_or_404

from .identity import get_identity_provider
from .models import JiraIssue, JiraIssueLink, JiraSprint, JiraStatus, ModuleUser


def visible_issues_for(user):
    profile = get_identity_provider().get_profile(user)

    if profile is None or profile.role != ModuleUser.Role.INTERN:
        return JiraIssue.objects.none()

    if not profile.owner_ref or not profile.owner_ref.strip():
        return JiraIssue.objects.none()

    return JiraIssue.objects.filter(
        project__is_enabled=True,
        owner_ref=profile.owner_ref,
    )

def get_issue(user, key):
    visible = visible_issues_for(user)
    visible_links = JiraIssueLink.objects.filter(
        to_key__in=visible.values("issue_key"),
    ).order_by("pk")

    issues = visible.select_related(
        "project", "status", "sprint", "assignee"
    ).prefetch_related(
        Prefetch("links", queryset=visible_links, to_attr="visible_links"),
    )
    return get_object_or_404(issues, issue_key=key)


def get_board(user, project_key=None):
    visible = visible_issues_for(user).filter(sprint__state=JiraSprint.State.ACTIVE)
    if project_key is not None:
        visible = visible.filter(project__project_key=project_key)

    sprint = (
        JiraSprint.objects.filter(pk__in=visible.values("sprint_id"))
        .order_by(F("start_date").desc(nulls_last=True), "jira_id")
        .first()
    )
    if sprint is None:
        return {"sprint": None, "columns": [], "synced_at": None}

    category_order = Case(
        When(status__category=JiraStatus.Category.TODO, then=0),
        When(status__category=JiraStatus.Category.IN_PROGRESS, then=1),
        When(status__category=JiraStatus.Category.DONE, then=2),
        default=3,
    )
    issues = (
        visible.filter(sprint=sprint)
        .select_related("status", "assignee")
        .order_by(
            category_order,
            "status__position",
            "status_id",
            F("rank").asc(nulls_last=True),
            "issue_key",
        )
    )

    columns = {}
    synced_at = None
    for issue in issues:
        if issue.status_id not in columns:
            columns[issue.status_id] = {
                "status": issue.status.name,
                "category": issue.status.category,
                "issues": [],
            }
        columns[issue.status_id]["issues"].append(issue)
        if synced_at is None or issue.synced_at > synced_at:
            synced_at = issue.synced_at

    return {"sprint": sprint, "columns": list(columns.values()), "synced_at": synced_at}


def get_backlog(user, filters=None, sort="rank", page=1, *, page_size=20):
    issues = _backlog_issues_for(user).exclude(sprint__state=JiraSprint.State.ACTIVE)

    filter_fields = {
        "assignee": "assignee__account_id",
        "status": "status__jira_id",
        "type": "issue_type",
    }
    for name, value in (filters or {}).items():
        if name not in filter_fields:
            raise ValueError(f"Неизвестный фильтр: {name}")
        if value is not None and value != "":
            issues = issues.filter(**{filter_fields[name]: value})

    sort_fields = {
        "rank": (F("rank").asc(nulls_last=True), "issue_key"),
        "updated": ("-updated_jira", "issue_key"),
        "key": ("issue_key",),
        "priority": (F("priority_order").asc(nulls_last=True), "issue_key"),
    }
    if sort not in sort_fields:
        raise ValueError(f"Неизвестная сортировка: {sort}")
    if not 1 <= page_size <= 100:
        raise ValueError("Размер страницы должен быть от 1 до 100.")

    ordered = issues.select_related("status", "assignee").order_by(*sort_fields[sort])
    paginator = Paginator(ordered, page_size)
    current_page = paginator.page(page)

    return {
        "count": paginator.count,
        "results": list(current_page.object_list),
        "synced_at": issues.aggregate(latest=Max("synced_at"))["latest"],
    }




def _backlog_issues_for(user):
    return visible_issues_for(user).exclude(
        sprint__state=JiraSprint.State.ACTIVE
    )


def get_backlog_filter_options(user):
    issues = _backlog_issues_for(user)

    return {
        "statuses": list(
            issues.order_by("status__name", "status__jira_id")
            .values_list("status__jira_id", "status__name")
            .distinct()
        ),
        "types": list(
            issues.order_by("issue_type")
            .values_list("issue_type", flat=True)
            .distinct()
        ),
        "assignees": list(
            issues.filter(assignee__isnull=False)
            .order_by("assignee__display_name", "assignee__account_id")
            .values_list("assignee__account_id", "assignee__display_name")
            .distinct()
        ),
    }