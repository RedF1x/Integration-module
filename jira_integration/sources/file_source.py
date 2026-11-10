"""FileSource: читает сохранённые данные из папки (тесты и страховочное демо).

Спринт 1: читает файлы в формате DTO (fixtures/dto/*.json), каждый файл это
объект {"projects": [...], "issues": [...]}. Когда в спринте 2 появится
нормализатор, добавим чтение fixtures/raw/ через него.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from jira_integration.dto import IssueDTO, ProjectDTO, SprintDTO, parse_iso
from jira_integration.sources.base import IssueSource, SourceError


class FileSource(IssueSource):
    def __init__(self, directory: str | Path):
        self.directory = Path(directory)
        self._issues: list[IssueDTO] = []
        self._projects: list[ProjectDTO] = []
        self._load()

    def _load(self) -> None:
        if not self.directory.is_dir():
            raise SourceError(f"Папка с данными не найдена: {self.directory}")
        files = sorted(self.directory.glob("*.json"))
        if not files:
            raise SourceError(f"В {self.directory} нет *.json")
        for path in files:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    raise ValueError("Expected an object with projects and issues")
                for name in ("projects", "issues"):
                    if not isinstance(data.get(name), list):
                        raise ValueError(f"{name} must be a list")
                    if any(not isinstance(item, dict) for item in data[name]):
                        raise ValueError(f"{name} must contain objects")
                self._projects += [ProjectDTO.from_dict(p) for p in data["projects"]]
                self._issues += [IssueDTO.from_dict(i) for i in data["issues"]]
            except (ValueError, KeyError) as exc:
                # сообщение без содержимого задач
                raise SourceError(f"Файл {path.name} не разобран: {type(exc).__name__}") from exc

    def projects(self) -> list[ProjectDTO]:
        return list(self._projects)

    def sprints(self, project_key: str) -> list[SprintDTO]:
        seen: dict[str, SprintDTO] = {}
        for issue in self._issues:
            if issue.project_key == project_key and issue.sprint:
                seen[issue.sprint.jira_id] = issue.sprint
        return list(seen.values())

    def issues(self, since: Optional[datetime] = None) -> Iterable[IssueDTO]:
        for issue in self._issues:
            if since is None or parse_iso(issue.updated_at) >= since:
                yield issue

    def issue_detail(self, key: str) -> Optional[IssueDTO]:
        return next((i for i in self._issues if i.key == key), None)
