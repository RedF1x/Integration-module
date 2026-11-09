from django.conf import settings
from django.db import models
from django.utils import timezone


class JiraProject(models.Model):
    jira_id = models.TextField(unique=True)
    project_key = models.TextField(unique=True)
    name = models.TextField()
    is_enabled = models.BooleanField(default=False)

    class Meta:
        db_table = "jira_project"

    def __str__(self):
        return self.project_key


class JiraStatus(models.Model):
    class Category(models.TextChoices):
        TODO = "todo", "К выполнению"
        IN_PROGRESS = "in_progress", "В работе"
        DONE = "done", "Готово"

    jira_id = models.TextField(unique=True)
    name = models.TextField()
    category = models.CharField(max_length=11, choices=Category.choices)
    position = models.IntegerField(default=0)

    class Meta:
        db_table = "jira_status"

    def __str__(self):
        return self.name


class JiraUser(models.Model):
    account_id = models.TextField(unique=True)
    display_name = models.TextField()
    email = models.EmailField(blank=True, null=True)
    avatar_url = models.TextField(blank=True, null=True)

    class Meta:
        db_table = "jira_user"

    def __str__(self):
        return self.display_name

class JiraSprint(models.Model):
    class State(models.TextChoices):
        FUTURE = "future", "Запланирован"
        ACTIVE = "active", "Активен"
        CLOSED = "closed", "Завершён"

    jira_id = models.TextField(unique=True)
    project = models.ForeignKey(
        JiraProject,
        on_delete=models.PROTECT,
        related_name="sprints",
    )
    name = models.TextField()
    state = models.CharField(max_length=6, choices=State.choices)
    start_date = models.DateTimeField(null=True, blank=True)
    end_date = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "jira_sprint"

    def __str__(self):
        return self.name


class JiraIssue(models.Model):
    jira_id = models.TextField(unique=True)
    issue_key = models.TextField(unique=True)
    project = models.ForeignKey(
        JiraProject,
        on_delete=models.PROTECT,
        related_name="issues",
    )
    sprint = models.ForeignKey(
        JiraSprint,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="issues",
    )
    status = models.ForeignKey(
        JiraStatus,
        on_delete=models.PROTECT,
        related_name="issues",
    )
    assignee = models.ForeignKey(
        JiraUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_issues",
    )
    owner_ref = models.TextField(null=True, blank=True, db_index=True)

    summary = models.TextField()
    issue_type = models.TextField()
    priority = models.TextField(null=True, blank=True)
    priority_order = models.IntegerField(null=True, blank=True)
    description_html = models.TextField(null=True, blank=True)
    labels = models.JSONField(default=list, blank=True)
    custom_fields = models.JSONField(default=dict, blank=True)
    rank = models.TextField(null=True, blank=True)

    updated_jira = models.DateTimeField(db_index=True)
    synced_at = models.DateTimeField()

    class Meta:
        db_table = "jira_issue"
        indexes = [
            models.Index(fields=["sprint", "status"], name="jira_issue_sprint_status_idx"),
        ]

    def __str__(self):
        return self.issue_key

class JiraComment(models.Model):
    jira_id = models.TextField(unique=True)
    issue = models.ForeignKey(
        JiraIssue,
        on_delete=models.CASCADE,
        related_name="comments",
    )
    author = models.ForeignKey(
        JiraUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="comments",
    )
    body_html = models.TextField()
    created_jira = models.DateTimeField()

    class Meta:
        db_table = "jira_comment"


class JiraIssueLink(models.Model):
    class Direction(models.TextChoices):
        INWARD = "inward", "Входящая"
        OUTWARD = "outward", "Исходящая"

    from_issue = models.ForeignKey(
        JiraIssue,
        on_delete=models.CASCADE,
        related_name="links",
    )
    to_key = models.TextField()
    link_type = models.TextField()
    direction = models.CharField(max_length=7, choices=Direction.choices)

    class Meta:
        db_table = "jira_issue_link"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(direction__in=["inward", "outward"]),
                name="jira_link_direction_valid",
            ),
            models.UniqueConstraint(
                fields=["from_issue", "to_key", "link_type", "direction"],
                name="jira_link_unique_relation",
            ),
        ]


class JiraFieldDef(models.Model):
    class Purpose(models.TextChoices):
        DISPLAY = "display", "Показывать практиканту"
        INTERN_DESCRIPTION = "intern_description", "Описание для практиканта"
        POLICY_FLAG = "policy_flag", "Проверка видимости"
        OWNER = "owner", "Определение владельца"

    jira_field_id = models.TextField(unique=True)
    name = models.TextField()
    value_type = models.TextField()
    purpose = models.CharField(max_length=18, choices=Purpose.choices)
    is_enabled = models.BooleanField(default=False)

    class Meta:
        db_table = "jira_field_def"

    def __str__(self):
        return f"{self.name} ({self.jira_field_id})"


class JiraVisibilityRule(models.Model):
    class Source(models.TextChoices):
        LABEL = "label", "Метка Jira"
        CUSTOM_FIELD = "custom_field", "Кастомное поле Jira"

    project = models.ForeignKey(
        JiraProject,
        on_delete=models.CASCADE,
        related_name="visibility_rules",
    )
    source = models.CharField(max_length=12, choices=Source.choices)
    field_def = models.ForeignKey(
        JiraFieldDef,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="visibility_rules",
    )
    expected_value = models.JSONField()
    is_enabled = models.BooleanField(default=False)

    class Meta:
        db_table = "jira_visibility_rule"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(source__in=["label", "custom_field"]),
                name="jira_rule_source_valid",
            ),
        ]

class ModuleUser(models.Model):
    class Role(models.TextChoices):
        INTERN = "intern", "Практикант"
        STAFF = "staff", "Сотрудник"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="jira_module_profile",
    )
    jira_user = models.OneToOneField(
        JiraUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="module_profile",
    )
    role = models.CharField(max_length=6, choices=Role.choices)
    owner_ref = models.TextField(null=True, blank=True)
    is_active = models.BooleanField(default=False)

    class Meta:
        db_table = "jira_module_user"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(role__in=["intern", "staff"]),
                name="jira_module_user_role_valid",
            ),
        ]


class JiraSyncRun(models.Model):
    class Status(models.TextChoices):
        RUNNING = "running", "Выполняется"
        SUCCESS = "success", "Завершён успешно"
        FAILED = "failed", "Завершён с ошибкой"

    class Source(models.TextChoices):
        MOCK = "mock", "Файловый источник"
        REST = "rest", "Jira REST API"

    class Mode(models.TextChoices):
        FULL = "full", "Полная загрузка"
        INCREMENTAL = "incremental", "Загрузка изменений"

    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=7,
        choices=Status.choices,
        default=Status.RUNNING,
    )
    source = models.CharField(max_length=4, choices=Source.choices)
    mode = models.CharField(max_length=11, choices=Mode.choices)
    requested_by = models.ForeignKey(
        ModuleUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="requested_sync_runs",
    )
    created_count = models.IntegerField(default=0)
    updated_count = models.IntegerField(default=0)
    deleted_count = models.IntegerField(default=0)
    failed_count = models.IntegerField(default=0)
    error_code = models.TextField(null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "jira_sync_run"