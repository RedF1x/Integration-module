from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import timedelta

from jira_integration.normalizer.issues import normalize
from jira_integration.sources.config import DataConfig
from jira_integration.sources.raw import RawSource


@dataclass
class SyncResult:
    mode: str
    processed: int = 0
    created: int = 0
    updated: int = 0
    deleted: int = 0
    denied: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def status(self):
        return "failed" if self.failed else "success"

    def add_error(self, stage, exc):
        self.failed += 1
        # Только фиксированная стадия и класс исключения: без входных значений.
        if len(self.errors) < 20:
            self.errors.append(f"{stage}: {type(exc).__name__}")


def run_sync(source, mode="full", *, store=None, dry_run=False, since=None):
    """Raw → policy → normalize → atomic upsert/explicit revoke.

    dry-run читает локальные правила, но не изменяет БД и журнал.
    Полная очистка по отсутствию и расписание относятся к спринту 3.
    """
    if not isinstance(source, RawSource):
        raise ValueError(
            "sync требует raw-источник; DTO FileSource только для тестов DTO"
        )
    if mode not in {"full", "incremental"}:
        raise ValueError("mode должен быть full или incremental")
    if since is not None and (mode != "incremental" or since.utcoffset() is None):
        raise ValueError("since допустим только для incremental с часовым поясом")
    if source.kind not in {"rest", "mock"}:
        raise ValueError("Неизвестный тип источника")
    config = getattr(source, "config", DataConfig())
    if store is None:
        from .real_store import RealStore

        store = RealStore(source.kind)
    result = SyncResult(mode)
    with nullcontext() if dry_run else store.lock():
        if mode == "incremental":
            last = store.last_success()
            if last is None:
                raise ValueError(
                    "Перед incremental нужен успешный full этого источника"
                )
            # Пользовательский --since не должен пропускать неполученные изменения.
            since = min(since, last.started_at) if since else last.started_at
            since -= timedelta(seconds=config.overlap_seconds)
        run_id = None if dry_run else store.start_run(mode)
        stage = "policy"
        try:
            policy = store.policy()
            if not dry_run:
                result.deleted += store.apply_local_restrictions(policy, config)
            stage = "catalog"
            source.reset()
            catalog = source.catalog()
            if not dry_run:
                store.refresh_catalog(catalog)
            seen = set()

            def process(raw):
                try:
                    decision = policy.evaluate(raw)
                    seen.add(decision.jira_id)
                    if decision.allowed:
                        if not dry_run:
                            store.close_previous_owner(decision)
                        comments = (
                            source.comments(raw["key"]) if config.comments else ()
                        )
                        dto = normalize(raw, catalog, policy, config, comments)
                        if not dry_run:
                            if store.upsert_allowed(dto, decision, catalog, raw):
                                result.created += 1
                            else:
                                result.updated += 1
                    else:
                        result.denied += 1
                        if not dry_run:
                            result.deleted += store.revoke(decision.jira_id)
                    result.processed += 1
                except Exception as exc:
                    result.add_error("issue", exc)

            stage = "source"
            for raw in source.raw_issues(since, extra_fields=policy.field_ids):
                process(raw)
            if mode == "incremental":
                # Проверяем старые разрешённые задачи даже при изменении только
                # локального правила/состояния спринта, не затронувшем Jira updated.
                for identity, key in store.stored_keys():
                    if identity in seen:
                        continue
                    try:
                        raw = source.raw_issue_detail(
                            key, extra_fields=policy.field_ids
                        )
                        if str(raw["id"]) != identity:
                            raise ValueError("ID задачи изменился")
                        process(raw)
                    except Exception as exc:
                        result.add_error("recheck", exc)
        except Exception as exc:
            result.add_error(stage, exc)
        except BaseException as exc:
            result.add_error("interrupted", exc)
            raise
        finally:
            if run_id is not None:
                store.finish_run(run_id, result)
    return result
