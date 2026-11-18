from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from jira_integration.models import JiraUser, ModuleUser


class Command(BaseCommand):
    help = "Привязывает профиль модуля к пользователю Jira."

    def add_arguments(self, parser):
        parser.add_argument("username", help="Логин пользователя Django")
        parser.add_argument(
            "--owner-from-assignee",
            action="store_true",
            help="Заполнить owner_ref значением account_id для правила по исполнителю",
        )

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

        if profile.jira_user_id not in (None, jira_user.pk):
            raise CommandError("У профиля уже есть другая привязка к Jira.")

        if (
            ModuleUser.objects.filter(jira_user=jira_user)
            .exclude(pk=profile.pk)
            .exists()
        ):
            raise CommandError("Этот пользователь Jira уже связан с другим профилем.")

        update_fields = []

        if options["owner_from_assignee"]:
            if not jira_user.account_id or not jira_user.account_id.strip():
                raise CommandError("У пользователя Jira пустой account_id.")

            current_owner = profile.owner_ref
            if (
                current_owner
                and current_owner.strip()
                and current_owner != jira_user.account_id
            ):
                raise CommandError(
                    "owner_ref уже содержит другое значение. "
                    "Сначала проверь правило доступа."
                )

            if current_owner != jira_user.account_id:
                profile.owner_ref = jira_user.account_id
                update_fields.append("owner_ref")

        if profile.jira_user_id != jira_user.pk:
            profile.jira_user = jira_user
            update_fields.append("jira_user")

        if not update_fields:
            self.stdout.write("Эта привязка уже существует.")
            return

        profile.save(update_fields=update_fields)
        self.stdout.write(self.style.SUCCESS("Привязка профиля сохранена."))