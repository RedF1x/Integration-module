from pathlib import Path

import pytest

from jira_integration.sources.config import DataConfig
from jira_integration.sources.raw_file_source import RawFileSource

RAW = Path(__file__).resolve().parents[2] / "fixtures/raw"


@pytest.fixture(autouse=True)
def isolated_data_environment(monkeypatch):
    # Локальный .env разработчика не должен включать живую Jira во время тестов.
    for name in (
        "JIRA_API_URL",
        "JIRA_BASE_URL",
        "JIRA_API_TOKEN",
        "JIRA_EMAIL",
        "JIRA_RAW_MANIFEST",
        "OWNER_SOURCE",
        "JIRA_PROJECT_KEYS",
        "JIRA_BOARD_ID",
        "JIRA_OVERLAP_SECONDS",
        "JIRA_PRIORITY_IDS",
        "JIRA_INCLUDE_DESCRIPTION",
        "JIRA_INCLUDE_COMMENTS",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("JIRA_SOURCE", "mock")


@pytest.fixture
def raw_source():
    return RawFileSource(RAW / "sprint2.json", DataConfig())
