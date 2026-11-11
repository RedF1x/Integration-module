from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError

from jira_integration.sources import SourceError, get_source
from jira_integration.sync.service import run_sync


class Command(BaseCommand):
    help = "Загружает подготовленные тестовые DTO из файлов в базу данных."

    def add_arguments(self, parser):
        parser.add_argument(
            "--full", action="store_true", help="полная загрузка (по умолчанию)"
        )
        parser.add_argument(
            "--dry-run", action="store_true", help="проверить данные без записи"
        )

    def handle(self, *args, **options):
        try:
            result = run_sync(get_source(), "full", dry_run=options["dry_run"])
        except SourceError as exc:
            raise CommandError(str(exc)) from exc
        except (DatabaseError, OSError) as exc:
            raise CommandError(
                f"Синхронизация не запущена: {type(exc).__name__}"
            ) from exc

        prefix = "dry-run " if options["dry_run"] else ""
        self.stdout.write(
            f"{prefix}{result.status}: обработано {result.processed}, "
            f"создано {result.created}, обновлено {result.updated}, ошибок {result.failed}"
        )
        for error in result.errors:
            self.stderr.write(error)
        if result.failed:
            raise CommandError("Синхронизация завершилась с ошибками.")
