"""Источники raw для одного общего конвейера нормализации и политики."""

import os
from pathlib import Path

from .base import SourceError
from .config import DataConfig
from .raw_file_source import RawFileSource
from .rest_source import RestSource

DEFAULT_MANIFEST = Path(__file__).resolve().parents[2] / "fixtures/raw/sprint2.json"


def get_source():
    config = DataConfig.from_env()
    kind = os.environ.get("JIRA_SOURCE", "mock").lower()
    if kind == "mock":
        return RawFileSource(
            os.environ.get("JIRA_RAW_MANIFEST", DEFAULT_MANIFEST), config
        )
    if kind == "rest":
        return RestSource(config)
    raise SourceError("Неизвестный JIRA_SOURCE; допустимы mock и rest")
