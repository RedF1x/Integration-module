import os
import re
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from jira_integration.normalizer.catalog import build_catalog

from .auth import BasicTokenAuth
from .base import SourceError
from .http import JiraHTTP, offset_pages, token_pages
from .raw import RawSource


class RestSource(RawSource):
    kind = "rest"

    def __init__(self, config, *, http=None):
        self.config = config
        self.http = http or JiraHTTP(
            os.environ.get("JIRA_API_URL") or os.environ.get("JIRA_BASE_URL", ""),
            BasicTokenAuth(
                os.environ.get("JIRA_EMAIL", ""), os.environ.get("JIRA_API_TOKEN", "")
            ),
        )
        self._catalog = None
        self._jql_zone = None

    def close(self):
        self.http.close()

    def reset(self):
        self._catalog = None
        self._jql_zone = None

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
                actor = self.http.request("GET", "/rest/api/3/myself")
                self._jql_zone = ZoneInfo(actor["timeZone"])
            except (KeyError, TypeError, ZoneInfoNotFoundError):
                raise SourceError(
                    "Не определён часовой пояс JQL-пользователя"
                ) from None
            self._catalog = build_catalog(
                self.http.request("GET", "/rest/api/3/project/SCRUM"),
                self.http.request("GET", "/rest/api/3/field"),
                self.http.request("GET", "/rest/agile/1.0/board/1/configuration"),
                self._list("/rest/agile/1.0/board/1/sprint"),
                self.http.request("GET", "/rest/api/3/project/SCRUM/statuses"),
                self._list("/rest/api/3/priority/search"),
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

    def raw_issues(self, since=None, *, extra_fields=()):
        fields = self._fields(extra_fields)
        jql = 'project = "SCRUM"'
        if since is not None:
            if since.utcoffset() is None:
                raise SourceError("since требует часовой пояс")
            # JQL интерпретирует дату в часовом поясе технической учётки.
            # Округление вниз к минуте расширяет окно, а не теряет изменения.
            stamp = since.astimezone(self._jql_zone).strftime("%Y-%m-%d %H:%M")
            jql += f' AND updated >= "{stamp}"'
        jql += " ORDER BY key ASC"
        body = {
            "jql": jql,
            "fields": fields,
            "expand": "renderedFields",
            "maxResults": 50,
        }

        def fetch(token):
            page = dict(body)
            if token is not None:
                page["nextPageToken"] = token
            return self.http.request("POST", "/rest/api/3/search/jql", json=page)

        yield from token_pages(fetch)

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
