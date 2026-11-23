from django.shortcuts import render

from .decorators import intern_required
from .selectors import get_backlog_filter_options, get_issue


@intern_required
def index(request):
    return render(request, "jira_integration/index.html")


@intern_required
def board(request):
    return render(request, "jira_integration/board.html")


@intern_required
def backlog(request):
    return render(
        request,
        "jira_integration/backlog.html",
        {"filter_options": get_backlog_filter_options(request.user)},
    )


@intern_required
def issue_detail(request, key):
    issue = get_issue(request.user, key)
    return render(
        request,
        "jira_integration/issue.html",
        {"issue_key": issue.issue_key},
    )