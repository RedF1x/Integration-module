"""Read-only HTTP для Jira Cloud."""

import math
import random
import re
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import requests

from .base import SourceError
from .config import api_url


class JiraStatusError(SourceError):
    def __init__(self, status):
        super().__init__(f"Jira: HTTP {status}")
        self.status = status


class InvalidCursor(SourceError):
    """Jira отклонила продолжение поиска."""


class JiraUnavailable(SourceError):
    pass


class RetryLater(SourceError):
    def __init__(self, seconds):
        self.seconds = math.ceil(seconds)
        super().__init__("Jira: достигнут лимит ожидания, запуск отложен")


def read_retry_after(value):
    try:
        delay = float(value)
    except ValueError:
        try:
            delay = (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            raise SourceError("Jira: неверный Retry-After") from None
    if not math.isfinite(delay):
        raise SourceError("Jira: неверный Retry-After")
    return max(0, delay)


class JiraHTTP:
    def __init__(
        self,
        base_url,
        auth,
        *,
        session=None,
        sleep=time.sleep,
        retries=3,
        max_wait=120,
        timeout=(5, 30),
        clock=time.monotonic,
    ):
        self.base_url = api_url(base_url)
        self.session = session or requests.Session()
        # Не позволяем .netrc незаметно заменить явно заданную авторизацию.
        self.session.trust_env = False
        self.session.auth = auth.as_requests_auth()
        self.session.headers.update({"Accept": "application/json"})
        self.sleep = sleep
        self.retries = retries
        self.max_wait = max_wait
        self.timeout = timeout
        self.clock = clock
        self.not_before = {}
        self.defer_rate_limits = False

    def close(self):
        self.session.close()

    def request(self, method, path, **kwargs):
        if (
            method not in {"GET", "POST"}
            or not path.startswith("/rest/")
            or (
                method == "POST"
                and path
                not in {"/rest/api/3/search/jql", "/rest/api/3/issue/bulkfetch"}
            )
        ):
            raise SourceError("Недопустимая операция источника")
        route = (
            method,
            re.sub(r"(/rest/api/3/issue/)[^/]+", r"\1{id}", path)
            if method == "GET"
            else path,
        )
        # Один HTTP-отправитель на воркер. Запас относительно порога метода Jira.
        spacing = 1 / (140 if route == ("GET", "/rest/api/3/issue/{id}") else 80)
        for attempt in range(self.retries + 1):
            wait = self.not_before.get(route, 0) - self.clock()
            if wait > self.max_wait:
                raise RetryLater(wait)
            if wait > 0:
                self.sleep(math.ceil(wait) if attempt else wait)
            self.not_before[route] = self.clock() + spacing
            response = None
            try:
                response = self.session.request(
                    method,
                    self.base_url + path,
                    timeout=self.timeout,
                    allow_redirects=False,
                    **kwargs,
                )
            except (requests.Timeout, requests.ConnectionError):
                if attempt == self.retries:
                    raise JiraUnavailable("Jira: соединение недоступно") from None
            except requests.RequestException:
                raise SourceError("Jira: HTTP-запрос не выполнен") from None
            if response is not None:
                status = response.status_code
                if status == 200:
                    try:
                        return response.json()
                    except ValueError:
                        raise SourceError("Jira: некорректный JSON") from None
                    finally:
                        response.close()
                retry_after = response.headers.get("Retry-After")
                response.close()
                if status != 429 and not 500 <= status < 600:
                    raise JiraStatusError(status)
            else:
                retry_after = None
            delay = 2**attempt + random.uniform(0, 0.25)
            if retry_after:
                delay = max(delay, read_retry_after(retry_after))
            self.not_before[route] = self.clock() + delay
            if (
                response is not None
                and response.status_code == 429
                and self.defer_rate_limits
            ):
                raise RetryLater(delay)
            if delay > self.max_wait or (attempt == self.retries and retry_after):
                raise RetryLater(delay)
            if attempt == self.retries:
                raise JiraUnavailable(f"Jira: исчерпаны повторы HTTP {status}")


def offset_pages(fetch, key="values"):
    """Используется REST и mock: конец подтверждается метаданными страницы."""
    start = 0
    seen = set()
    expected_total = None
    for _ in range(10000):
        data = fetch(start)
        if not isinstance(data, dict) or data.get("startAt") != start:
            raise SourceError("Jira: нарушен порядок страниц")
        values = data.get(key)
        total = data.get("total")
        if not isinstance(values, list) or type(total) is not int or total < 0:
            raise SourceError("Jira: неполная страница")
        if expected_total is not None and total != expected_total:
            raise SourceError("Jira: список изменился во время обхода")
        expected_total = total
        for item in values:
            if not isinstance(item, dict) or "id" not in item:
                raise SourceError("Jira: элемент без ID")
            identity = str(item["id"])
            if identity in seen:
                raise SourceError("Jira: повтор ID при обходе")
            seen.add(identity)
            yield item
        start += len(values)
        if start > total:
            raise SourceError("Jira: размер списка не совпадает с total")
        if start == total:
            if data.get("isLast") is False:
                raise SourceError("Jira: противоречивый конец списка")
            return
        if not values or data.get("isLast") is True:
            raise SourceError("Jira: обход списка оборван")
    raise SourceError("Jira: превышен лимит страниц")


def token_pages(fetch):
    token = None
    tokens = set()
    ids = set()
    for _ in range(10000):
        data = fetch(token)
        if not isinstance(data, dict) or not isinstance(data.get("issues"), list):
            raise SourceError("Jira: некорректная страница поиска")
        for raw in data["issues"]:
            if not isinstance(raw, dict) or not raw.get("id"):
                raise SourceError("Jira: задача без ID")
            identity = str(raw["id"])
            if identity in ids:
                raise SourceError("Jira: повтор задачи при обходе")
            ids.add(identity)
            yield raw
        next_token = data.get("nextPageToken")
        if data.get("isLast") is True and not next_token:
            return
        if (
            data.get("isLast") is True
            or not isinstance(next_token, str)
            or not next_token
            or next_token in tokens
        ):
            raise SourceError("Jira: некорректный курсор поиска")
        tokens.add(next_token)
        token = next_token
    raise SourceError("Jira: превышен лимит страниц поиска")
