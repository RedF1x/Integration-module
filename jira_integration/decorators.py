from functools import wraps

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import render

from .identity import get_identity_provider
from .models import ModuleUser


def intern_required(view):
    @login_required
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        profile = get_identity_provider().get_profile(request.user)
        if profile is None:
            raise PermissionDenied

        if profile.role == ModuleUser.Role.STAFF:
            return render(
                request,
                "jira_integration/staff.html",
                {"jira_url": settings.JIRA_BASE_URL},
            )

        if profile.role == ModuleUser.Role.INTERN:
            return view(request, *args, **kwargs)

        raise PermissionDenied

    return wrapped


def api_role_required(role):
    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return JsonResponse(
                    {"error": "unauthorized", "message": "Требуется вход."},
                    status=401,
                )

            profile = get_identity_provider().get_profile(request.user)
            if profile is None or profile.role != role:
                return JsonResponse(
                    {"error": "forbidden", "message": "Недостаточно прав."},
                    status=403,
                )

            return view(request, *args, **kwargs)

        return wrapped

    return decorator


intern_api_required = api_role_required(ModuleUser.Role.INTERN)
staff_required = api_role_required(ModuleUser.Role.STAFF)