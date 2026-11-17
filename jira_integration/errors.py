from django.http import JsonResponse
from django.views import defaults


def page_not_found(request, exception):
    if request.path_info.startswith("/jira/api/"):
        return JsonResponse(
            {"error": "not_found", "message": "Адрес не найден."},
            status=404,
        )

    return defaults.page_not_found(request, exception)


def server_error(request):
    if request.path_info.startswith("/jira/api/"):
        return JsonResponse(
            {"error": "server_error", "message": "Не удалось выполнить запрос."},
            status=500,
        )

    return defaults.server_error(request)