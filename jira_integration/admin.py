from django.contrib import admin

from .models import (
    JiraComment,
    JiraFieldDef,
    JiraIssue,
    JiraIssueLink,
    JiraProject,
    JiraSprint,
    JiraStatus,
    JiraSyncRun,
    JiraUser,
    JiraVisibilityRule,
    ModuleUser,
)


@admin.register(JiraIssue)
class JiraIssueAdmin(admin.ModelAdmin):
    list_display = ("issue_key", "summary", "project", "status", "assignee")
    search_fields = ("issue_key", "summary")
    list_filter = ("project", "status")
    list_select_related = ("project", "status", "assignee")


@admin.register(JiraSyncRun)
class JiraSyncRunAdmin(admin.ModelAdmin):
    list_display = ("started_at", "source", "mode", "status", "failed_count")
    list_filter = ("status", "mode")
    ordering = ("-started_at",)


admin.site.register([
    JiraComment,
    JiraFieldDef,
    JiraIssueLink,
    JiraProject,
    JiraSprint,
    JiraStatus,
    JiraUser,
    JiraVisibilityRule,
    ModuleUser,
])