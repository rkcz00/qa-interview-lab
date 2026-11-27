import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

from apps.assessments.section_provenance_v1 import backfill_section_progress


class Migration(migrations.Migration):
    dependencies = [
        ("assessments", "0004_user_progress_state"),
        ("learning", "0003_topic_sections"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="TopicSectionProgress",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("read_at", models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ("section", models.ForeignKey(editable=False, on_delete=django.db.models.deletion.PROTECT,
                                            related_name="progress", to="learning.topicsection")),
                ("user", models.ForeignKey(editable=False, on_delete=django.db.models.deletion.CASCADE,
                                         related_name="section_progress", to=settings.AUTH_USER_MODEL)),
            ],
            options={"constraints": [models.UniqueConstraint(fields=("user", "section"), name="section_progress_owner_unique")]},
        ),
        migrations.RunPython(backfill_section_progress, migrations.RunPython.noop),
    ]
