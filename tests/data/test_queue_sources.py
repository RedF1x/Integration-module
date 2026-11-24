import json
from datetime import UTC, datetime, timedelta

import pytest
import responses

from jira_integration.sources.config import DataConfig
from jira_integration.sources.http import InvalidCursor, JiraStatusError, RetryLater
from jira_integration.sources.rest_source import RestSource

from .test_rest_source import BASE, catalog_routes, client, fixture


def make_source(clock=None):
    options = {"clock": clock} if clock is not None else {}
    return RestSource(DataConfig(), http=client(), **options)


@responses.activate
def test_fixed_search_window_and_opaque_continuation():
    catalog_routes()
    url = BASE + "/rest/api/3/search/jql"
    responses.post(url, json={"issues": [{"id": "1"}], "nextPageToken": "opaque"})
    responses.post(url, json={"issues": [], "isLast": True})
    begin = datetime(2026, 11, 11, 3, 15, tzinfo=UTC)
    until = begin + timedelta(minutes=5)
    source = make_source()
    rows, token = source.issue_page(begin, until)
    assert rows == [{"id": "1"}]
    assert source.issue_page(begin, until, token) == ([], None)
    body = json.loads(responses.calls[-1].request.body)
    assert body["nextPageToken"] == "opaque"
    assert body["maxResults"] == 50
    assert 'updated >= "2026-11-11 08:15"' in body["jql"]
    assert 'updated < "2026-11-11 08:20"' in body["jql"]


@responses.activate
def test_rejected_continuation_is_distinct_from_first_request_failure():
    catalog_routes()
    responses.post(BASE + "/rest/api/3/search/jql", status=400)
    source = make_source()
    with pytest.raises(InvalidCursor):
        source.issue_page(None, None, "expired")
    with pytest.raises(JiraStatusError):
        source.issue_page(None, None)


@responses.activate
def test_cached_metadata_expires_but_sprints_refresh_each_reset():
    catalog_routes()
    clock = [1]
    source = make_source(lambda: clock[0])
    source.catalog()
    for name in ["sprints_page_1.json", "sprints_page_2.json"]:
        responses.get(BASE + "/rest/agile/1.0/board/1/sprint", json=fixture(name))
    source.reset()
    source.catalog()
    assert len(responses.calls) == 10
    clock[0] += 901
    catalog_routes()
    source.reset()
    source.catalog()
    assert (
        sum(c.request.url == BASE + "/rest/api/3/field" for c in responses.calls) == 2
    )


@responses.activate
def test_bulk_read_one_post_and_confirm_absence_individually():
    catalog_routes()
    url = BASE + "/rest/api/3/issue/bulkfetch"
    row = fixture("issue_active.json")
    responses.post(url, json={"issues": [row], "issueErrors": []})
    responses.get(BASE + "/rest/api/3/issue/20000", status=404)
    source = make_source()
    assert list(source.bulk_issues([row["id"], "20000"])) == [
        ([row], set()),
        ([], {"20000"}),
    ]
    body = json.loads(responses.calls[-2].request.body)
    assert body["issueIdsOrKeys"] == [row["id"], "20000"]
    assert body["expand"] == ["renderedFields"]


@responses.activate
def test_scope_failure_is_not_a_delete_signal():
    catalog_routes()
    responses.post(BASE + "/rest/api/3/issue/bulkfetch", json={"issues": []})
    responses.get(BASE + "/rest/api/3/issue/20000", status=403)
    with pytest.raises(JiraStatusError, match="403"):
        list(make_source().bulk_issues(["20000"]))


@responses.activate
def test_rate_limit_applies_to_route_and_blocks_premature_repeat():
    first = BASE + "/rest/api/3/issue/123"
    responses.get(first, status=429, headers={"Retry-After": "300"})
    http = client()
    with pytest.raises(RetryLater) as err:
        http.request("GET", "/rest/api/3/issue/123")
    assert err.value.seconds == 300
    with pytest.raises(RetryLater):
        http.request("GET", "/rest/api/3/issue/456")
    assert len(responses.calls) == 1


def test_mock_full_incremental_and_bulk_share_ids(raw_source):
    rows, token = raw_source.issue_page(None, None)
    assert len(rows) == 12 and token is None
    stamp = datetime(2099, 1, 1, tzinfo=UTC)
    assert raw_source.issue_page(stamp, stamp + timedelta(minutes=1)) == ([], None)
    assert list(raw_source.bulk_issues([rows[0]["id"], "999999"])) == [
        ([rows[0]], {"999999"})
    ]


@responses.activate
def test_worker_defers_even_short_retry_after_without_sleeping():
    path = "/rest/api/3/field"
    responses.get(BASE + path, status=429, headers={"Retry-After": "3"})
    http = client(lambda seconds: pytest.fail("Воркер не должен спать после 429"))
    http.defer_rate_limits = True
    with pytest.raises(RetryLater) as exc:
        http.request("GET", path)
    assert exc.value.seconds == 3
    assert len(responses.calls) == 1
