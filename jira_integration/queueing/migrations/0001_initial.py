import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [("jira_integration", "0001_initial")]

    operations = [
        migrations.CreateModel(
            name="SyncCursor",
            fields=[
                (
                    "source",
                    models.CharField(max_length=4, primary_key=True, serialize=False),
                ),
                ("watermark", models.DateTimeField(null=True)),
                ("last_full", models.DateTimeField(null=True)),
                ("next_due", models.DateTimeField(default=django.utils.timezone.now)),
                ("phase", models.CharField(default="idle", max_length=8)),
                ("page_token", models.TextField(blank=True, default="")),
                ("token_hashes", models.JSONField(default=list)),
                ("cursor_restarts", models.PositiveSmallIntegerField(default=0)),
                ("reconcile_pk", models.PositiveBigIntegerField(default=0)),
                (
                    "run",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="jira_integration.jirasyncrun",
                    ),
                ),
            ],
        ),
    ]
