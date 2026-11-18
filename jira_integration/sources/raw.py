"""Внутренний интерфейс raw. IssueSource/IssueDTO спринта 1 сохранены."""

from abc import ABC, abstractmethod


class RawSource(ABC):
    kind: str

    def reset(self):
        """Начало нового обхода: сбросить кэш справочников, если он есть."""
        pass

    @abstractmethod
    def catalog(self): ...

    @abstractmethod
    def raw_issues(self, since=None, *, extra_fields=()): ...

    @abstractmethod
    def raw_issue_detail(self, key, *, extra_fields=()): ...

    @abstractmethod
    def comments(self, key): ...

    def close(self):
        pass
