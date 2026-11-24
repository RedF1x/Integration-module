from django.db import models
from django.utils import timezone


class SyncCursor(models.Model):
    source = models.CharField(primary_key=True, max_length=4)
    run = models.ForeignKey(
        "jira_integration.JiraSyncRun", null=True, on_delete=models.SET_NULL
    )
    watermark = models.DateTimeField(null=True)
    last_full = models.DateTimeField(null=True)
    next_due = models.DateTimeField(default=timezone.now)
    phase = models.CharField(max_length=8, default="idle")
    page_token = models.TextField(default="", blank=True)
    token_hashes = models.JSONField(default=list)
    cursor_restarts = models.PositiveSmallIntegerField(default=0)
    reconcile_pk = models.PositiveBigIntegerField(default=0)
