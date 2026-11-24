"""Одна страница поиска или одна пачка сверки под общей блокировкой sync."""

from datetime import timedelta
from hashlib import sha256

from django.core.exceptions import ValidationError
from django.db import DataError, transaction
from django.db.models import F
from django.utils import timezone

from jira_integration.models import JiraIssue, JiraSyncRun
from jira_integration.normalizer.issues import normalize
from jira_integration.queueing.models import SyncCursor
from jira_integration.sources.http import InvalidCursor, JiraUnavailable, RetryLater
from jira_integration.sync.real_store import RealStore


def _begin(state, store, now, reconcile_seconds):
    full = not state.last_full or now >= state.last_full + timedelta(
        seconds=reconcile_seconds
    )
    state.run_id = store.start_run("full" if full else "incremental")
    state.phase = "search"
    state.page_token = ""
    state.token_hashes = []
    state.cursor_restarts = 0
    state.reconcile_pk = 0
    state.next_due = now
    state.save()


def _record_errors(run, ids):
    if ids:
        # Только проверенные числовые ID. Повторная сверка одной задачи не удваивает счётчик.
        known = set(run.error_message.split()) if run.error_message else set()
        known.update(ids)
        run.error_message = " ".join(sorted(known))
        run.failed_count = len(known)
        run.save(update_fields=["error_message", "failed_count"])


def _revoke_and_prepare(rows, missing, policy, store, run):
    allowed = []
    invalid = []
    deleted = 0
    # Отзыв должен пережить ошибку последующей нормализации или чтения комментариев.
    with transaction.atomic():
        for identity in missing:
            deleted += store.revoke(identity)
        for raw in rows:
            try:
                decision = policy.evaluate(raw)
            except (KeyError, ValueError, TypeError, AttributeError):
                deleted += store.revoke(raw["id"])
                invalid.append(raw["id"])
                continue
            if decision.allowed:
                store.close_previous_owner(decision)
                allowed.append((raw, decision))
            else:
                deleted += store.revoke(decision.jira_id)
        if deleted:
            JiraSyncRun.objects.filter(pk=run.pk).update(
                deleted_count=F("deleted_count") + deleted
            )
        _record_errors(run, invalid)
    return allowed


def _finish(state, poll_seconds):
    run = state.run
    run.status = "failed" if run.failed_count else "success"
    if run.failed_count:
        run.error_code = "invalid_issue"
    run.finished_at = timezone.now()
    run.save(update_fields=["status", "finished_at", "error_code"])
    if run.status == "success":
        state.watermark = run.started_at
        if run.mode == "full":
            state.last_full = run.finished_at
    state.phase = "idle"
    state.run = None
    state.token_hashes = []
    state.page_token = ""
    base = run.finished_at if run.failed_count else run.started_at
    state.next_due = base + timedelta(seconds=poll_seconds)
    state.save()
    return state.next_due <= run.finished_at


def _process(state, source, store, poll_seconds):
    run = state.run
    policy = store.policy()
    first_page = state.phase == "search" and not state.page_token
    if first_page:
        source.reset()
        with transaction.atomic():
            deleted = store.apply_local_restrictions(policy, source.config)
            JiraSyncRun.objects.filter(pk=run.pk).update(
                deleted_count=F("deleted_count") + deleted
            )
    catalog = source.catalog()
    if first_page:
        store.refresh_catalog(catalog)

    token = None
    last_pk = None
    expected = None
    if state.phase == "verify":
        # Последняя страница полного поиска уже успешно записана.
        batch = list(
            JiraIssue.objects.filter(
                project__project_key="SCRUM",
                pk__gt=state.reconcile_pk,
                synced_at__lt=run.started_at,
            )
            .order_by("pk")
            .values_list("pk", "jira_id")[:50]
        )
        if not batch:
            with transaction.atomic():
                return _finish(state, poll_seconds)
        ids = [identity for _, identity in batch]
        expected = set(ids)
        last_pk = batch[-1][0]
        chunks = source.bulk_issues(ids, extra_fields=policy.field_ids)
    else:
        since = until = None
        if run.mode == "incremental":
            since = state.watermark - timedelta(seconds=source.config.overlap_seconds)
            until = run.started_at.replace(second=0, microsecond=0)
        rows, token = source.issue_page(
            since, until, state.page_token or None, extra_fields=policy.field_ids
        )
        if token:
            digest = sha256(token.encode()).hexdigest()
            if digest in state.token_hashes:
                raise ValueError("Повтор курсора Jira")
            state.token_hashes.append(digest)
        chunks = [(rows, set())]
    allowed = []
    for rows, missing in chunks:
        ids = [raw["id"] for raw in rows] + list(missing)
        if any(
            not isinstance(i, str) or not i.isascii() or not i.isdigit() for i in ids
        ):
            raise ValueError("Некорректный ID задачи")
        if len(ids) != len(set(ids)):
            raise ValueError("Повтор ID в ответе Jira")
        if expected is not None:
            if not expected.issuperset(ids):
                raise ValueError("Неожиданный ID при сверке")
            expected.difference_update(ids)
        allowed.extend(_revoke_and_prepare(rows, missing, policy, store, run))
    if expected:
        raise ValueError("Неполный ответ пакетной сверки")
    prepared = []
    invalid = []
    for raw, decision in allowed:
        try:
            comments = source.comments(raw["key"]) if source.config.comments else ()
            dto = normalize(raw, catalog, policy, source.config, comments)
        except (KeyError, ValueError, TypeError, AttributeError, ValidationError):
            invalid.append(decision.jira_id)
        else:
            prepared.append((dto, decision, raw))

    with transaction.atomic():
        created = updated = 0
        for dto, decision, raw in prepared:
            try:
                if store.upsert_allowed(dto, decision, catalog, raw):
                    created += 1
                else:
                    updated += 1
            except (
                KeyError,
                ValueError,
                TypeError,
                AttributeError,
                ValidationError,
                DataError,
            ):
                invalid.append(decision.jira_id)
        _record_errors(run, invalid)
        JiraSyncRun.objects.filter(pk=run.pk).update(
            created_count=F("created_count") + created,
            updated_count=F("updated_count") + updated,
        )
        if state.phase == "verify":
            state.reconcile_pk = last_pk
        elif token:
            state.page_token = token
        elif run.mode == "full":
            state.phase = "verify"
            state.page_token = ""
            state.token_hashes = []
        else:
            return _finish(state, poll_seconds)
        state.save()
    return True


def process_step(source, *, poll_seconds=60, reconcile_seconds=3600):
    """True — продолжение готово. Очередной тик восстанавливает потерянный вызов."""
    if min(poll_seconds, reconcile_seconds) < 1:
        raise ValueError("Интервалы должны быть положительными")
    store = RealStore(source.kind)
    with store.lock():
        now = timezone.now()
        with transaction.atomic():
            state, created = SyncCursor.objects.get_or_create(
                source=source.kind, defaults={"next_due": now}
            )
            if created and (
                SyncCursor.objects.exclude(pk=source.kind).exists()
                or (
                    JiraIssue.objects.filter(project__project_key="SCRUM").exists()
                    and JiraSyncRun.objects.exclude(source=source.kind).exists()
                )
            ):
                raise ValueError("Для mock и rest используйте разные базы данных")
        if now < state.next_due:
            return False
        if state.phase == "idle" or not state.run_id or state.run.status != "running":
            with transaction.atomic():
                _begin(state, store, now, reconcile_seconds)
        try:
            return _process(state, source, store, poll_seconds)
        except (RetryLater, JiraUnavailable) as exc:
            delay = max(1, exc.seconds) if isinstance(exc, RetryLater) else poll_seconds
            state.next_due = timezone.now() + timedelta(seconds=delay)
            state.save(update_fields=["next_due"])
            return False
        except InvalidCursor:
            if (
                state.phase == "search"
                and state.page_token
                and not state.cursor_restarts
            ):
                state.cursor_restarts += 1
                state.page_token = ""
                state.token_hashes = []
                state.save(
                    update_fields=["cursor_restarts", "page_token", "token_hashes"]
                )
                return True
            code = "invalid_cursor"
        except Exception as exc:
            code = type(exc).__name__

        # Курсор успешной загрузки не сдвигается. Следующий тик повторит окно.
        with transaction.atomic():
            JiraSyncRun.objects.filter(pk=state.run_id).update(
                status="failed",
                finished_at=timezone.now(),
                failed_count=F("failed_count") + 1,
                error_code="sync_failed",
                error_message=state.run.error_message or code,
            )
            state.phase = "idle"
            state.run = None
            state.next_due = timezone.now() + timedelta(seconds=poll_seconds)
            state.save(update_fields=["phase", "run", "next_due"])
        raise RuntimeError(
            f"Обработка страницы Jira завершилась ошибкой ({code})"
        ) from None
