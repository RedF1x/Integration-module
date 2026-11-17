from dataclasses import dataclass, field

from requests.auth import HTTPBasicAuth

from .base import SourceError


@dataclass(frozen=True)
class BasicTokenAuth:
    email: str = field(repr=False)
    token: str = field(repr=False)

    def as_requests_auth(self):
        if not self.email or not self.token:
            raise SourceError("RestSource: нужны JIRA_EMAIL и JIRA_API_TOKEN")
        return HTTPBasicAuth(self.email, self.token)
