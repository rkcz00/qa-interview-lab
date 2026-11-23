from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("assessments", "0003_topic_progress"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="UserProgressState",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("generation", models.PositiveBigIntegerField(default=1, editable=False)),
                ("last_reset_request_id", models.UUIDField(editable=False, null=True)),
                ("last_reset_from_generation", models.PositiveBigIntegerField(editable=False, null=True)),
                ("user", models.OneToOneField(editable=False, on_delete=django.db.models.deletion.CASCADE, related_name="progress_state", to=settings.AUTH_USER_MODEL)),
            ],
            options={"constraints": [
                models.CheckConstraint(condition=models.Q(generation__gte=1), name="progress_generation_positive"),
                models.CheckConstraint(
                    condition=(
                        models.Q(last_reset_request_id__isnull=True, last_reset_from_generation__isnull=True)
                        | models.Q(last_reset_request_id__isnull=False, last_reset_from_generation__isnull=False,
                                   last_reset_from_generation__gte=1, generation=models.F("last_reset_from_generation") + 1)
                    ), name="progress_reset_receipt_valid",
                ),
            ]},
        ),
    ]
