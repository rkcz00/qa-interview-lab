import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


@pytest.mark.django_db(transaction=True)
def test_additive_practice_migration_preserves_existing_content_user_and_read_data():
    """DDL is limited to pytest's disposable PostgreSQL, never the development DB."""
    assert connection.settings_dict["NAME"].startswith("test_qil006_")
    executor = MigrationExecutor(connection)
    full_targets = executor.loader.graph.leaf_nodes()
    old_targets = [node for node in full_targets if node[0] != "practice"]
    executor.migrate([("practice", None)])
    try:
        old = executor.loader.project_state(old_targets).apps
        user = old.get_model("accounts", "User").objects.create(email="migration-practice@example.invalid", password="!")
        topic = old.get_model("learning", "Topic").objects.create(status="draft", revision=7)
        translations = old.get_model("learning", "TopicTranslation")
        for language in ("ru", "en"):
            translations.objects.create(topic_id=topic.pk, language=language, title=f"{language} original", article_body="Preserved body")
        mark = old.get_model("assessments", "TopicProgress").objects.create(user_id=user.pk, topic_id=topic.pk)
        executor = MigrationExecutor(connection)
        executor.migrate(full_targets)
        from apps.accounts.models import User
        from apps.assessments.models import TopicProgress
        from apps.learning.models import Topic
        from apps.practice.models import TopicPractice
        assert User.objects.get(pk=user.pk).email == "migration-practice@example.invalid"
        assert Topic.objects.get(pk=topic.pk).revision == 7
        assert list(Topic.objects.get(pk=topic.pk).translations.order_by("language").values_list("title", flat=True)) == ["en original", "ru original"]
        assert TopicProgress.objects.get(pk=mark.pk).article_read_at == mark.article_read_at
        assert not TopicPractice.objects.exists()
    finally:
        MigrationExecutor(connection).migrate(full_targets)
