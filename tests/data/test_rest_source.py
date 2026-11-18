import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import requests
import responses

from jira_integration.sources.auth import BasicTokenAuth
from jira_integration.sources.base import SourceError
from jira_integration.sources.config import DataConfig
from jira_integration.sources.http import JiraHTTP, offset_pages, token_pages
from jira_integration.sources.rest_source import RestSource

RAW = Path(__file__).resolve().parents[2] / "fixtures/raw"
BASE = "https://example.atlassian.net"


def fixture(name):
    return json.loads((RAW / name).read_text(encoding="utf-8"))


def client(sleep=lambda _: None):
    return JiraHTTP(
        BASE, BasicTokenAuth("test@example.test", "TEST-TOKEN"), sleep=sleep
    )


def catalog_routes():
    for path, filename in [
        ("/rest/api/3/myself", "myself.json"),
        ("/rest/api/3/project/SCRUM", "project.json"),
        ("/rest/api/3/field", "fields.json"),
        ("/rest/agile/1.0/board/1/configuration", "board_configuration.json"),
        ("/rest/agile/1.0/board/1/sprint", "sprints_page_1.json"),
        ("/rest/agile/1.0/board/1/sprint", "sprints_page_2.json"),
        ("/rest/api/3/project/SCRUM/statuses", "project_statuses.json"),
        ("/rest/api/3/priority/search", "priorities.json"),
    ]:
        responses.get(BASE + path, json=fixture(filename))


@responses.activate
def test_search_paginates_all_seven_pages_and_keeps_revoked_tasks(raw_source):
    catalog_routes()
    for i in range(1, 8):
        responses.post(
            BASE + "/rest/api/3/search/jql", json=fixture(f"search_page_{i}.json")
        )
    source = RestSource(DataConfig(), http=client())
    results = list(source.raw_issues(datetime(2026, 11, 11, tzinfo=UTC)))
    assert len(results) == 12 and len({r["id"] for r in results}) == 12
    calls = [c for c in responses.calls if c.request.method == "POST"]
    bodies = [json.loads(c.request.body) for c in calls]
    assert 'updated >= "2026-11-11 05:00"' in bodies[0]["jql"]
    assert "intern-visible" not in bodies[0]["jql"]
    assert "nextPageToken" not in bodies[0]
    assert bodies[1]["nextPageToken"] == fixture("search_page_1.json")["nextPageToken"]
    assert "description" not in bodies[0]["fields"]
    assert "attachment" not in bodies[0]["fields"]


@responses.activate
def test_retry_after_and_503_then_success():
    waits = []
    responses.get(BASE + "/rest/api/3/field", status=429, headers={"Retry-After": "4"})
    responses.get(BASE + "/rest/api/3/field", status=503)
    responses.get(BASE + "/rest/api/3/field", json=[])
    assert client(waits.append).request("GET", "/rest/api/3/field") == []
    assert len(waits) == 2 and waits[0] >= 4


@pytest.mark.parametrize("status", [301, 401, 403, 404])
@responses.activate
def test_errors_do_not_leak_or_retry(status):
    responses.get(
        BASE + "/rest/api/3/field",
        status=status,
        body="SECRET body TEST-TOKEN",
        headers={"Location": "https://evil.test"},
    )
    with pytest.raises(SourceError) as error:
        client().request("GET", "/rest/api/3/field")
    assert len(responses.calls) == 1
    assert "SECRET" not in str(error.value) and "TEST-TOKEN" not in str(error.value)


@responses.activate
def test_retry_limit_and_timeout():
    responses.get(BASE + "/rest/api/3/field", body=requests.Timeout("SECRET"))
    with pytest.raises(SourceError, match="соединение"):
        client().request("GET", "/rest/api/3/field")
    assert len(responses.calls) == 4


@responses.activate
def test_excessive_retry_after_does_not_retry_early():
    responses.get(
        BASE + "/rest/api/3/field", status=429, headers={"Retry-After": "9999"}
    )
    with pytest.raises(SourceError, match="лимит"):
        client(lambda _: pytest.fail("must not sleep")).request(
            "GET", "/rest/api/3/field"
        )
    assert len(responses.calls) == 1


def test_empty_search_and_broken_cursor():
    assert list(token_pages(lambda _: {"issues": [], "isLast": True})) == []
    with pytest.raises(SourceError, match="курсор"):
        list(token_pages(lambda _: {"issues": [], "nextPageToken": "same"}))
    with pytest.raises(SourceError, match="курсор"):
        list(token_pages(lambda _: {"issues": []}))


def test_offset_page_does_not_treat_truncation_as_completion():
    with pytest.raises(SourceError, match="оборван"):
        list(offset_pages(lambda start: {"startAt": start, "total": 3, "values": []}))


@responses.activate
def test_partial_comment_pages_fail():
    responses.get(
        BASE + "/rest/api/3/issue/SCRUM-11/comment",
        json=fixture("comments_page_1.json"),
    )
    responses.get(BASE + "/rest/api/3/issue/SCRUM-11/comment", status=403)
    with pytest.raises(SourceError):
        RestSource(DataConfig(), http=client()).comments("SCRUM-11")


def test_read_only_client_rejects_write_before_network():
    with pytest.raises(SourceError):
        client().request("POST", "/rest/api/3/issue", json={})
