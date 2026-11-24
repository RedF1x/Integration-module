from django.apps import AppConfig


class QueueingConfig(AppConfig):
    name = "jira_integration.queueing"
    label = "jira_queue"
    verbose_name = "Очередь синхронизации Jira"
