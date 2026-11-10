from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from jira_integration.models import JiraUser, ModuleUser


class Command(BaseCommand):
    help = "Привязывает профиль модуля к пользователю Jira."

    def add_arguments(self, parser):
        parser.add_argument("username", help="Логин пользователя Django")
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--account-id", help="Точный account_id пользователя Jira")
        group.add_argument(
            "--by-email",
            action="store_true",
            help="Найти пользователя Jira по почте из учётной записи Django",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        try:
            profile = ModuleUser.objects.select_for_update().get(
                user__username=options["username"]
            )
        except ModuleUser.DoesNotExist:
            raise CommandError("Профиль модуля для этого логина не найден.")

        candidates = JiraUser.objects.select_for_update()
        if options["by_email"]:
            email = profile.user.email.strip()
            if not email:
                raise CommandError("У пользователя нет email. Укажи --account-id.")
            candidates = candidates.filter(email__iexact=email)
        else:
            candidates = candidates.filter(account_id=options["account_id"])

        try:
            jira_user = candidates.get()
        except JiraUser.DoesNotExist:
            raise CommandError("Пользователь Jira не найден в локальной базе.")
        except JiraUser.MultipleObjectsReturned:
            raise CommandError("Найдено несколько совпадений. Укажи --account-id.")

        if profile.jira_user_id == jira_user.pk:
            self.stdout.write("Эта привязка уже существует.")
            return

        if profile.jira_user_id is not None:
            raise CommandError("У профиля уже есть другая привязка к Jira.")

        if ModuleUser.objects.filter(jira_user=jira_user).exists():
            raise CommandError("Этот пользователь Jira уже связан с другим профилем.")

        profile.jira_user = jira_user
        profile.save(update_fields=["jira_user"])
        self.stdout.write(self.style.SUCCESS("Пользователь Jira привязан."))