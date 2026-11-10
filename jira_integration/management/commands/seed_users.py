from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from jira_integration.models import ModuleUser


class Command(BaseCommand):
    help = "Создаёт локальные тестовые аккаунты практикантов и сотрудника."

    @transaction.atomic
    def handle(self, *args, **options):
        User = get_user_model()
        accounts = [
            ("demo_intern_1", ModuleUser.Role.INTERN),
            ("demo_intern_2", ModuleUser.Role.INTERN),
            ("demo_staff", ModuleUser.Role.STAFF),
        ]
        created_count = 0

        for username, role in accounts:
            user, created = User.objects.get_or_create(username=username)

            if created:
                user.set_unusable_password()
                user.save(update_fields=["password"])
                ModuleUser.objects.create(user=user, role=role, is_active=True)
                created_count += 1
            elif not ModuleUser.objects.filter(user=user, role=role).exists():
                raise CommandError(
                    f"Логин {username} уже занят пользователем "
                    "без ожидаемого профиля. Проверь его вручную."
                )

        self.stdout.write(self.style.SUCCESS(f"Создано аккаунтов: {created_count}"))