import os
import re
import time
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from jira_integration.normalizer.catalog import build_catalog

from .auth import BasicTokenAuth
from .base import SourceError
from .http import InvalidCursor, JiraHTTP, JiraStatusError, offset_pages, token_pages
from .raw import RawSource


class RestSource(RawSource):
    kind = "rest"

    def __init__(self, config, *, http=None, clock=time.monotonic):
        self.config = config
        self.http = http or JiraHTTP(
            os.environ.get("JIRA_API_URL") or os.environ.get("JIRA_BASE_URL", ""),
            BasicTokenAuth(
                os.environ.get("JIRA_EMAIL", ""), os.environ.get("JIRA_API_TOKEN", "")
            ),
        )
        self._catalog = None
        self._jql_zone = None
        self._stable = {}
        self._clock = clock

    def close(self):
        self.http.close()

    def reset(self):
        self._catalog = None

    def _metadata(self, path, *, paginated=False):
        entry = self._stable.get(path)
        if entry is None or self._clock() >= entry[0]:
            value = self._list(path) if paginated else self.http.request("GET", path)
            entry = self._clock() + 15 * 60, value
            self._stable[path] = entry
        return entry[1]

    def _list(self, path, key="values", **params):
        return list(
            offset_pages(
                lambda start: self.http.request(
                    "GET", path, params={**params, "startAt": start, "maxResults": 50}
                ),
                key,
            )
        )

    def catalog(self):
        if self._catalog is None:
            try:
                actor = self._metadata("/rest/api/3/myself")
                self._jql_zone = ZoneInfo(actor["timeZone"])
            except (KeyError, TypeError, ZoneInfoNotFoundError):
                raise SourceError(
                    "Не определён часовой пояс JQL-пользователя"
                ) from None
            self._catalog = build_catalog(
                self._metadata("/rest/api/3/project/SCRUM"),
                self._metadata("/rest/api/3/field"),
                self._metadata("/rest/agile/1.0/board/1/configuration"),
                self._list("/rest/agile/1.0/board/1/sprint"),
                self._metadata("/rest/api/3/project/SCRUM/statuses"),
                self._metadata("/rest/api/3/priority/search", paginated=True),
                self.config.priority_ids,
            )
        return self._catalog

    def _fields(self, extra):
        catalog = self.catalog()
        fields = {
            "project",
            "summary",
            "issuetype",
            "priority",
            "status",
            "updated",
            "assignee",
            "labels",
            "issuelinks",
            catalog.sprint_field,
            catalog.rank_field,
        }
        if self.config.descriptions:
            fields.add("description")
        for name in extra:
            if not re.fullmatch(r"customfield_[0-9]+", name):
                raise SourceError("Некорректный ID пользовательского поля")
            fields.add(name)
        return sorted(fields)

    def _search_body(self, since, until, extra_fields):
        fields = self._fields(extra_fields)
        jql = 'project = "SCRUM"'
        for boundary, operator in [(since, ">="), (until, "<")]:
            if boundary is not None:
                if boundary.utcoffset() is None:
                    raise SourceError("Граница поиска требует часовой пояс")
                stamp = boundary.astimezone(self._jql_zone).strftime("%Y-%m-%d %H:%M")
                jql += f' AND updated {operator} "{stamp}"'
        jql += " ORDER BY key ASC"
        return {
            "jql": jql,
            "fields": fields,
            "expand": "renderedFields",
            "maxResults": 50,
        }

    def _search_page(self, body, token):
        if token is not None:
            body = {**body, "nextPageToken": token}
        try:
            return self.http.request("POST", "/rest/api/3/search/jql", json=body)
        except JiraStatusError as exc:
            if token is not None and exc.status == 400:
                raise InvalidCursor("Jira отклонила курсор поиска") from None
            raise

    def raw_issues(self, since=None, *, extra_fields=()):
        body = self._search_body(since, None, extra_fields)
        yield from token_pages(lambda token: self._search_page(body, token))

    def issue_page(self, since, until, token=None, *, extra_fields=()):
        body = self._search_body(since, until, extra_fields)
        data = self._search_page(body, token)
        if not isinstance(data, dict) or not isinstance(data.get("issues"), list):
            raise SourceError("Jira: неполная страница поиска")
        issues = data["issues"]
        identities = set()
        for issue in issues:
            if not isinstance(issue, dict) or not isinstance(issue.get("id"), str):
                raise SourceError("Jira: отсутствует ID задачи")
            if not issue["id"] or issue["id"] in identities:
                raise SourceError("Jira: неверный ID задачи")
            identities.add(issue["id"])
        following = data.get("nextPageToken")
        if data.get("isLast") is True and not following:
            return issues, None
        if (
            data.get("isLast") is True
            or not isinstance(following, str)
            or not following
            or following == token
        ):
            raise SourceError("Jira: некорректный курсор поиска")
        return issues, following

    def bulk_issues(self, ids, *, extra_fields=()):
        ids = list(ids)
        if (
            not 1 <= len(ids) <= 50
            or any(not isinstance(i, str) or not re.fullmatch("[0-9]+", i) for i in ids)
            or len(set(ids)) != len(ids)
        ):
            raise SourceError("Для сверки требуется от 1 до 50 разных Jira ID")
        fields = self._fields(extra_fields)
        data = self.http.request(
            "POST",
            "/rest/api/3/issue/bulkfetch",
            json={
                "issueIdsOrKeys": ids,
                "fields": fields,
                "expand": ["renderedFields"],
            },
        )
        if not isinstance(data, dict) or not isinstance(data.get("issues"), list):
            raise SourceError("Jira: неверный ответ сверки")
        rows = list(data["issues"])
        remaining = set(ids)
        for raw in rows:
            if not isinstance(raw, dict) or raw.get("id") not in remaining:
                raise SourceError("Jira: неожиданный ID при сверке")
            remaining.remove(raw["id"])
        # Пропуск в bulkfetch сам по себе не является доказательством отзыва.
        yield rows, set()
        for identity in sorted(remaining):
            try:
                raw = self.http.request(
                    "GET",
                    "/rest/api/3/issue/" + identity,
                    params={"fields": ",".join(fields), "expand": "renderedFields"},
                )
            except JiraStatusError as exc:
                if exc.status != 404:
                    raise
                yield [], {identity}
                continue
            if not isinstance(raw, dict) or raw.get("id") != identity:
                raise SourceError("Jira: подтвердить ID задачи не удалось")
            yield [raw], set()

    def raw_issue_detail(self, key, *, extra_fields=()):
        if not re.fullmatch(r"SCRUM-[0-9]+", key):
            raise SourceError("Ключ задачи вне области SCRUM")
        return self.http.request(
            "GET",
            "/rest/api/3/issue/" + quote(key, safe=""),
            params={
                "fields": ",".join(self._fields(extra_fields)),
                "expand": "renderedFields",
            },
        )

    def comments(self, key):
        if not re.fullmatch(r"SCRUM-[0-9]+", key):
            raise SourceError("Ключ задачи вне области SCRUM")
        return self._list(
            f"/rest/api/3/issue/{key}/comment", "comments", expand="renderedBody"
        )
