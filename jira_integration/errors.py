from django.http import JsonResponse
from django.shortcuts import render
from django.views import defaults


def permission_denied(request, exception):
    if request.path_info.startswith("/jira/api/"):
        return JsonResponse(
            {"error": "forbidden", "message": "Недостаточно прав."},
            status=403,
        )

    if request.path_info.startswith("/jira/"):
        return render(request, "jira_integration/403.html", status=403)

    return defaults.permission_denied(request, exception)


def page_not_found(request, exception):
    if request.path_info.startswith("/jira/api/"):
        return JsonResponse(
            {"error": "not_found", "message": "Адрес не найден."},
            status=404,
        )

    if request.path_info.startswith("/jira/"):
        return render(request, "jira_integration/404.html", status=404)

    return defaults.page_not_found(request, exception)


def server_error(request):
    if request.path_info.startswith("/jira/api/"):
        return JsonResponse(
            {"error": "server_error", "message": "Не удалось выполнить запрос."},
            status=500,
        )

    return defaults.server_error(request)