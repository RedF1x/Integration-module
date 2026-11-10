"""Интерфейс источника данных. Владелец: Бэкенд А."""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Iterable, Optional

from jira_integration.dto import IssueDTO, ProjectDTO, SprintDTO


class SourceError(RuntimeError):
    """Ошибка источника (сеть, авторизация, битые данные)."""


class IssueSource(ABC):
    """Всё, что умеет отдавать данные модулю. Остальной код знает только этот интерфейс."""

    @abstractmethod
    def projects(self) -> list[ProjectDTO]: ...

    @abstractmethod
    def sprints(self, project_key: str) -> list[SprintDTO]: ...

    @abstractmethod
    def issues(self, since: Optional[datetime] = None) -> Iterable[IssueDTO]:
        """Задачи, обновлённые не раньше `since` (None = все)."""

    @abstractmethod
    def issue_detail(self, key: str) -> Optional[IssueDTO]: ...
