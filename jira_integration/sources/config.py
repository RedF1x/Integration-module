"""Настройки слоя А. Читаются из окружения после загрузки Django settings."""

import os
from dataclasses import dataclass
from urllib.parse import urlsplit

from .base import SourceError


@dataclass(frozen=True)
class DataConfig:
    project_key: str = "SCRUM"
    board_id: int = 1
    descriptions: bool = False
    comments: bool = False
    overlap_seconds: int = 300
    priority_ids: tuple[str, ...] = ("1", "2", "3", "4", "5")

    def __post_init__(self):
        if (self.project_key, self.board_id) != ("SCRUM", 1):
            raise SourceError("Спринт 2 поддерживает только SCRUM и доску 1")
        if not 60 <= self.overlap_seconds <= 86400:
            raise SourceError("JIRA_OVERLAP_SECONDS: допустимо 60..86400")
        if (
            not self.priority_ids
            or len(set(self.priority_ids)) != len(self.priority_ids)
            or not all(p.isdigit() for p in self.priority_ids)
        ):
            raise SourceError(
                "JIRA_PRIORITY_IDS: нужен список уникальных ID по убыванию важности"
            )

    @classmethod
    def from_env(cls):
        def flag(name):
            value = os.environ.get(name, "false").lower()
            if value not in {"true", "false"}:
                raise SourceError(f"{name}: требуется true или false")
            return value == "true"

        if os.environ.get("OWNER_SOURCE", "assignee") != "assignee":
            raise SourceError("Спринт 2 поддерживает OWNER_SOURCE=assignee")
        try:
            return cls(
                project_key=os.environ.get("JIRA_PROJECT_KEYS", "SCRUM"),
                board_id=int(os.environ.get("JIRA_BOARD_ID", "1")),
                descriptions=flag("JIRA_INCLUDE_DESCRIPTION"),
                comments=flag("JIRA_INCLUDE_COMMENTS"),
                overlap_seconds=int(os.environ.get("JIRA_OVERLAP_SECONDS", "300")),
                priority_ids=tuple(
                    os.environ.get("JIRA_PRIORITY_IDS", "1,2,3,4,5").split(",")
                ),
            )
        except ValueError:
            raise SourceError("Некорректное числовое значение настройки Jira") from None


def api_url(value):
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise SourceError("JIRA_API_URL: требуется HTTPS URL без учётных данных")
    return value.rstrip("/")
