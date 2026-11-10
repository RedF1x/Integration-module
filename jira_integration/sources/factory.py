"""Выбор источника по JIRA_SOURCE (mock | rest). Владелец: Бэкенд А."""
from __future__ import annotations

import os
from pathlib import Path

from jira_integration.sources.base import IssueSource, SourceError
from jira_integration.sources.file_source import FileSource

DEFAULT_MOCK_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "dto"


def get_source() -> IssueSource:
    kind = os.environ.get("JIRA_SOURCE", "mock").lower()
    if kind == "mock":
        return FileSource(os.environ.get("JIRA_MOCK_DIR", DEFAULT_MOCK_DIR))
    if kind == "rest":
        # RestSource появится в спринте 2 (задача А4)
        raise SourceError("JIRA_SOURCE=rest: RestSource ещё не реализован")
    raise SourceError(f"Неизвестное значение JIRA_SOURCE: {kind!r}")
