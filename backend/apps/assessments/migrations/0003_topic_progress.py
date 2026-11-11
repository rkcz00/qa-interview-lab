import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("assessments", "0002_attempt"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="TopicProgress",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("article_read_at", models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ("topic", models.ForeignKey(
                    editable=False, on_delete=django.db.models.deletion.PROTECT,
                    related_name="progress", to="learning.topic",
                )),
                ("user", models.ForeignKey(
                    editable=False, on_delete=django.db.models.deletion.CASCADE,
                    related_name="topic_progress", to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                "constraints": [models.UniqueConstraint(
                    fields=("user", "topic"), name="assessments_topic_progress_owner_unique",
                )],
            },
        ),
    ]
