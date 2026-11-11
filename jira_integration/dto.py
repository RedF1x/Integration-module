"""IssueDTO: единый формат задачи внутри модуля (контракт, раздел 0 ТЗ).

Владелец файла: Бэкенд А. Изменения только через PR с меткой `contract`,
одобряют оба бэкендера.

DTO не зависит от Django и БД. Даты хранятся строками ISO 8601
(как в контракте API); валидность проверяется при создании.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Optional

STATUS_CATEGORIES = ("todo", "in_progress", "done")
SPRINT_STATES = ("future", "active", "closed")
LINK_DIRECTIONS = ("inward", "outward")  # как в Jira; сверить с БД-схемой (CHECK по direction)


class DTOError(ValueError):
    """Ошибка структуры или значения при создании DTO."""


def parse_iso(value: str, field_name: str = "date") -> datetime:
    """Разбирает дату и время ISO 8601 с обязательным часовым поясом."""
    if not isinstance(value, str) or not value:
        raise DTOError(f"{field_name}: ожидалась строка ISO 8601")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DTOError(f"{field_name}: неверный формат даты {value!r}") from exc
    if parsed.utcoffset() is None:
        raise DTOError(f"{field_name}: требуется время с часовым поясом")
    return parsed


def _require(data: dict, key: str, where: str) -> Any:
    if not isinstance(data, dict):
        raise DTOError(f"{where}: ожидался словарь")
    value = data.get(key)
    if value is None or value == "":
        raise DTOError(f"{where}: обязательное поле {key!r} отсутствует")
    return value


@dataclass
class StatusDTO:
    jira_id: str  # id статуса в Jira (status.id); ключ для upsert в jira_status
    name: str
    category: str  # todo | in_progress | done

    def __post_init__(self) -> None:
        if self.category not in STATUS_CATEGORIES:
            raise DTOError(f"status.category: {self.category!r} не из {STATUS_CATEGORIES}")

    @classmethod
    def from_dict(cls, data: dict) -> "StatusDTO":
        return cls(jira_id=str(_require(data, "jira_id", "status")),
                   name=_require(data, "name", "status"),
                   category=_require(data, "category", "status"))


@dataclass
class UserDTO:
    account_id: str
    display_name: str
    email: Optional[str] = None  # в Jira может быть скрыт
    avatar_url: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict) -> "UserDTO":
        return cls(
            account_id=_require(data, "account_id", "user"),
            display_name=_require(data, "display_name", "user"),
            email=data.get("email") or None,
            avatar_url=data.get("avatar_url") or None,
        )


@dataclass
class SprintDTO:
    jira_id: str
    name: str
    state: str  # active | future | closed (как в Jira)
    start_date: Optional[str] = None
    end_date: Optional[str] = None

    def __post_init__(self) -> None:
        if self.state not in SPRINT_STATES:
            raise DTOError(f"sprint.state: {self.state!r} не из {SPRINT_STATES}")
        if self.start_date is not None:
            parse_iso(self.start_date, "sprint.start_date")
        if self.end_date is not None:
            parse_iso(self.end_date, "sprint.end_date")

    @classmethod
    def from_dict(cls, data: dict) -> "SprintDTO":
        return cls(
            jira_id=str(_require(data, "jira_id", "sprint")),
            name=_require(data, "name", "sprint"),
            state=_require(data, "state", "sprint"),
            start_date=data.get("start_date"),
            end_date=data.get("end_date"),
        )


@dataclass
class CommentDTO:
    jira_id: str  # добавлено на утверждении спринта 1: нужен для upsert комментариев
    author: UserDTO
    body_html: str  # только очищенный HTML
    created_at: str

    @classmethod
    def from_dict(cls, data: dict) -> "CommentDTO":
        created = _require(data, "created_at", "comment")
        parse_iso(created, "comment.created_at")
        return cls(
            jira_id=str(_require(data, "jira_id", "comment")),
            author=UserDTO.from_dict(_require(data, "author", "comment")),
            body_html=data.get("body_html") or "",
            created_at=created,
        )


@dataclass
class LinkDTO:
    link_type: str
    direction: str  # inward | outward
    target_key: str

    def __post_init__(self) -> None:
        if self.direction not in LINK_DIRECTIONS:
            raise DTOError(f"link.direction: {self.direction!r} не из {LINK_DIRECTIONS}")

    @classmethod
    def from_dict(cls, data: dict) -> "LinkDTO":
        return cls(
            link_type=_require(data, "link_type", "link"),
            direction=_require(data, "direction", "link"),
            target_key=_require(data, "target_key", "link"),
        )


@dataclass
class IssueDTO:
    jira_id: str
    key: str
    project_key: str
    summary: str
    issue_type: str
    status: StatusDTO
    updated_at: str  # ISO 8601
    priority: Optional[str] = None
    rank: Optional[str] = None
    assignee: Optional[UserDTO] = None
    sprint: Optional[SprintDTO] = None
    labels: list[str] = field(default_factory=list)
    description_html: Optional[str] = None  # очищенный HTML или None
    custom_fields: dict[str, Any] = field(default_factory=dict)  # только белый список
    comments: list[CommentDTO] = field(default_factory=list)
    links: list[LinkDTO] = field(default_factory=list)

    def __post_init__(self) -> None:
        parse_iso(self.updated_at, "updated_at")
        if not isinstance(self.labels, list) or not all(
            isinstance(label, str) for label in self.labels
        ):
            raise DTOError("labels: ожидался список строк")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "IssueDTO":
        where = "issue"
        jira_id = str(_require(data, "jira_id", where))
        assignee = data.get("assignee")
        sprint = data.get("sprint")
        for name in ("comments", "links"):
            value = data.get(name)
            if value is not None and not isinstance(value, list):
                raise DTOError(f"{name}: ожидался список объектов")
        custom_fields = data.get("custom_fields")
        if custom_fields is not None and not isinstance(custom_fields, dict):
            raise DTOError("custom_fields: ожидался словарь")
        return cls(
            jira_id=jira_id,
            key=_require(data, "key", where),
            project_key=_require(data, "project_key", where),
            summary=_require(data, "summary", where),
            issue_type=_require(data, "issue_type", where),
            status=StatusDTO.from_dict(_require(data, "status", where)),
            updated_at=_require(data, "updated_at", where),
            priority=data.get("priority"),
            rank=data.get("rank"),
            assignee=UserDTO.from_dict(assignee) if assignee is not None else None,
            sprint=SprintDTO.from_dict(sprint) if sprint is not None else None,
            labels=data.get("labels") if data.get("labels") is not None else [],
            description_html=data.get("description_html"),
            custom_fields=dict(data.get("custom_fields") or {}),
            comments=[CommentDTO.from_dict(c) for c in data.get("comments") or []],
            links=[LinkDTO.from_dict(x) for x in data.get("links") or []],
        )


@dataclass
class ProjectDTO:
    """Служебный DTO для IssueSource.projects(); в контракт API не входит."""
    jira_id: str  # id проекта в Jira (project.id); ключ для upsert в jira_project
    key: str
    name: str

    @classmethod
    def from_dict(cls, data: dict) -> "ProjectDTO":
        return cls(jira_id=str(_require(data, "jira_id", "project")),
                   key=_require(data, "key", "project"),
                   name=_require(data, "name", "project"))
