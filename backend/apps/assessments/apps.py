from django.apps import AppConfig
from django.db.models.signals import post_migrate


class AssessmentsConfig(AppConfig):
    name = "apps.assessments"
    verbose_name = "Вопросы и варианты"

    def ready(self):
        from apps.learning.permissions import sync_content_admin

        post_migrate.connect(sync_content_admin, sender=self, dispatch_uid="qil.content_admin")
