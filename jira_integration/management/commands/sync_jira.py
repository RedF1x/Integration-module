from django.core.management.base import BaseCommand, CommandError

from jira_integration.dto import parse_iso
from jira_integration.sources import get_source
from jira_integration.sync.service import run_sync


class Command(BaseCommand):
    help = "Загружает разрешённые задачи SCRUM из Jira или raw fixtures."

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--full", action="store_true")
        mode.add_argument("--incremental", action="store_true")
        parser.add_argument(
            "--since", help="ISO 8601 с часовым поясом; только incremental"
        )
        parser.add_argument(
            "--dry-run", action="store_true", help="без записи, с чтением правил"
        )

    def handle(self, *args, **options):
        source = None
        try:
            mode = "incremental" if options["incremental"] else "full"
            since = parse_iso(options["since"]) if options["since"] else None
            source = get_source()
            result = run_sync(source, mode, dry_run=options["dry_run"], since=since)
        except Exception as exc:
            # В CLI тоже исключаем вложенный HTTP traceback с входными данными.
            raise CommandError(f"Sync не запущен: {type(exc).__name__}") from None
        finally:
            if source is not None:
                source.close()
        prefix = "dry-run " if options["dry_run"] else ""
        self.stdout.write(
            f"{prefix}{result.status}: обработано {result.processed}, "
            f"создано {result.created}, обновлено {result.updated}, "
            f"удалено {result.deleted}, запрещено {result.denied}, ошибок {result.failed}"
        )
        if result.failed:
            self.stderr.write("; ".join(result.errors))
            raise CommandError("Синхронизация завершилась с ошибками")
