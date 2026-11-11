from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Protocol

from jira_integration.dto import IssueDTO, ProjectDTO
from jira_integration.sources.base import IssueSource

log = logging.getLogger(__name__)


@dataclass
class SyncResult:
    mode: str
    processed: int = 0
    created: int = 0
    updated: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        return "failed" if self.failed else "success"

    def add_error(self, message: str) -> None:
        self.failed += 1
        self.errors.append(message)
        log.warning("sync: %s", message)


class IssueStore(Protocol):
    def upsert_project(self, project: ProjectDTO) -> None: ...
    def upsert_issue(self, issue: IssueDTO) -> bool: ...
    def start_run(self, mode: str) -> int: ...
    def finish_run(self, run_id: int, result: SyncResult) -> None: ...


def run_sync(
    source: IssueSource,
    mode: str = "full",
    *,
    store: IssueStore | None = None,
    dry_run: bool = False,
) -> SyncResult:
    if mode != "full":
        raise ValueError("В первом спринте поддерживается только режим full.")

    result = SyncResult(mode)
    if dry_run:
        store = None
    elif store is None:
        from jira_integration.sync.django_store import DjangoStore

        store = DjangoStore()

    run_id = store.start_run(mode) if store is not None else None
    stage = "projects"
    try:
        projects = source.projects()
        project_keys = {project.key for project in projects}
        if store is not None:
            for project in projects:
                store.upsert_project(project)

        stage = "source"
        for issue in source.issues():
            if issue.project_key not in project_keys:
                result.add_error(f"{issue.key[:64]}: неизвестный проект")
                continue
            try:
                if store is not None:
                    if store.upsert_issue(issue):
                        result.created += 1
                    else:
                        result.updated += 1
                result.processed += 1
            except Exception as exc:
                result.add_error(f"{issue.key[:64]}: {type(exc).__name__}")
    except Exception as exc:
        result.add_error(f"{stage}: {type(exc).__name__}")
    finally:
        if store is not None and run_id is not None:
            store.finish_run(run_id, result)
    return result
