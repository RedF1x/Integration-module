import json
from pathlib import Path

from jira_integration.dto import parse_iso
from jira_integration.normalizer.catalog import build_catalog

from .base import SourceError
from .http import InvalidCursor, offset_pages
from .raw import RawSource


class RawFileSource(RawSource):
    kind = "mock"

    def __init__(self, manifest, config):
        self.config = config
        self.manifest_path = Path(manifest).resolve()
        self.root = self.manifest_path.parent
        self.manifest = self._read(self.manifest_path.name)
        if not isinstance(self.manifest, dict) or self.manifest.get("version") != 1:
            raise SourceError("Неизвестная версия raw-манифеста")

    def _read(self, name):
        try:
            path = (self.root / name).resolve()
            if not path.is_relative_to(self.root):
                raise ValueError("Путь вне каталога fixtures")
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            raise SourceError("Не удалось прочитать raw fixture") from None

    def _pages(self, names, key="values"):
        pages = iter(names)

        def fetch(start):
            try:
                return self._read(next(pages))
            except StopIteration:
                raise SourceError("В манифесте не хватает страниц") from None

        result = list(offset_pages(fetch, key))
        if next(pages, None) is not None:
            raise SourceError("В манифесте лишние страницы")
        return result

    def catalog(self):
        try:
            m = self.manifest
            return build_catalog(
                self._read(m["project"]),
                self._read(m["fields"]),
                self._read(m["board"]),
                self._pages(m["sprints"]),
                self._read(m["statuses"]),
                self._pages(m["priorities"]),
                self.config.priority_ids,
            )
        except (KeyError, TypeError):
            raise SourceError("Неполный raw-манифест") from None

    def raw_issues(self, since=None, *, extra_fields=()):
        seen = set()
        try:
            for filename in self.manifest["issues"]:
                raw = self._read(filename)
                identity = raw["id"]
                if identity in seen:
                    raise SourceError("Повтор задачи в raw-манифесте")
                seen.add(identity)
                if since is None or parse_iso(raw["fields"]["updated"]) >= since:
                    yield raw
        except (KeyError, TypeError, ValueError):
            raise SourceError("Некорректный raw-набор задач") from None

    def raw_issue_detail(self, key, *, extra_fields=()):
        for raw in self.raw_issues():
            if raw["key"] == key:
                return raw
        raise SourceError("Задача отсутствует в raw-манифесте")

    def issue_page(self, since, until, token=None, *, extra_fields=()):
        # Mock-манифест мал: фильтруем его полностью и имитируем курсор Jira.
        rows = sorted(
            (
                r
                for r in self.raw_issues(since)
                if until is None or parse_iso(r["fields"]["updated"]) < until
            ),
            key=lambda r: r["key"],
        )
        start = 0
        if token is not None:
            if not isinstance(token, str) or not token.isascii() or not token.isdigit():
                raise InvalidCursor("Неверный mock-курсор")
            start = int(token)
            if start < 1 or start >= len(rows) or start % 50:
                raise InvalidCursor("Неверный mock-курсор")
        end = start + 50
        return rows[start:end], str(end) if end < len(rows) else None

    def bulk_issues(self, ids, *, extra_fields=()):
        wanted = set(ids)
        if not 1 <= len(wanted) <= 50:
            raise SourceError("Для сверки требуется от 1 до 50 Jira ID")
        rows = [r for r in self.raw_issues() if r["id"] in wanted]
        yield rows, wanted.difference(r["id"] for r in rows)

    def comments(self, key):
        names = self.manifest.get("comments", {}).get(key)
        if names is not None:
            return self._pages(names, "comments")
        raw = self.raw_issue_detail(key)
        data = raw["fields"].get("comment")
        if isinstance(data, dict) and data.get("total") == 0:
            return []
        raise SourceError("Для комментариев нет полного raw-набора")
