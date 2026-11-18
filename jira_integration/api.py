from django.core.paginator import EmptyPage
from django.http import Http404, JsonResponse

from .decorators import intern_api_required
from .models import JiraSyncRun
from .selectors import get_backlog, get_board, get_issue
from .serializers import serialize_card, serialize_issue, serialize_sprint


@intern_api_required
def backlog(request):
    if request.method != "GET":
        response = JsonResponse(
            {"error": "method_not_allowed", "message": "Используйте GET."},
            status=405,
        )
        response["Allow"] = "GET"
        return response

    allowed = {"sort", "assignee", "status", "type", "page"}
    if set(request.GET) - allowed:
        return JsonResponse(
            {"error": "invalid_parameters", "message": "Неизвестный параметр."},
            status=400,
        )

    sort = request.GET.get("sort") or "rank"
    if sort not in {"rank", "updated", "key", "priority"}:
        return JsonResponse(
            {"error": "invalid_sort", "message": "Неизвестная сортировка."},
            status=400,
        )

    try:
        page = int(request.GET.get("page", "1"))
    except ValueError:
        page = 0

    if page < 1:
        return JsonResponse(
            {"error": "invalid_page", "message": "Номер страницы должен быть целым от 1."},
            status=400,
        )

    filters = {
        name: request.GET[name]
        for name in ("assignee", "status", "type")
        if name in request.GET
    }

    try:
        result = get_backlog(request.user, filters=filters, sort=sort, page=page)
    except EmptyPage:
        return JsonResponse(
            {"error": "not_found", "message": "Страница не найдена."},
            status=404,
        )

    return JsonResponse({
        "count": result["count"],
        "results": [serialize_card(issue) for issue in result["results"]],
        "synced_at": result["synced_at"],
    })


@intern_api_required
def board(request):
    if request.method != "GET":
        response = JsonResponse(
            {"error": "method_not_allowed", "message": "Используйте GET."},
            status=405,
        )
        response["Allow"] = "GET"
        return response

    if set(request.GET) - {"project_key"}:
        return JsonResponse(
            {"error": "invalid_parameters", "message": "Неизвестный параметр."},
            status=400,
        )

    result = get_board(
        request.user,
        project_key=request.GET.get("project_key") or None,
    )

    return JsonResponse({
        "sprint": serialize_sprint(result["sprint"]),
        "columns": [
            {
                "status": column["status"],
                "category": column["category"],
                "issues": [serialize_card(issue) for issue in column["issues"]],
            }
            for column in result["columns"]
        ],
        "synced_at": result["synced_at"],
    })


@intern_api_required
def sync_status(request):
    if request.method != "GET":
        response = JsonResponse(
            {"error": "method_not_allowed", "message": "Используйте GET."},
            status=405,
        )
        response["Allow"] = "GET"
        return response

    latest = JiraSyncRun.objects.order_by("-started_at", "-pk").first()
    last_success = (
        JiraSyncRun.objects.filter(
            status=JiraSyncRun.Status.SUCCESS,
            finished_at__isnull=False,
        )
        .order_by("-finished_at", "-pk")
        .first()
    )

    return JsonResponse({
        "status": latest.status if latest else None,
        "started_at": latest.started_at if latest else None,
        "finished_at": latest.finished_at if latest else None,
        "synced_at": last_success.finished_at if last_success else None,
    })


@intern_api_required
def issue_detail(request, key):
    if request.method != "GET":
        response = JsonResponse(
            {"error": "method_not_allowed", "message": "Используйте GET."},
            status=405,
        )
        response["Allow"] = "GET"
        return response

    try:
        issue = get_issue(request.user, key)
    except Http404:
        return JsonResponse(
            {"error": "not_found", "message": "Задача не найдена."},
            status=404,
        )

    return JsonResponse(serialize_issue(issue))