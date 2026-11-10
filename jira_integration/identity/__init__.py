from typing import Protocol

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from jira_integration.models import ModuleUser

from .local import LocalIdentity


class IdentityProvider(Protocol):
    def get_profile(self, user) -> ModuleUser | None: ...


def get_identity_provider() -> IdentityProvider:
    if settings.JIRA_IDENTITY == "local":
        return LocalIdentity()

    raise ImproperlyConfigured(
        f"Неизвестное значение JIRA_IDENTITY: {settings.JIRA_IDENTITY!r}"
    )