import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone


@pytest.mark.django_db(transaction=True)
def test_sections_migration_copies_legacy_verbatim_and_preserves_all_learner_records():
    assert connection.settings_dict["NAME"].startswith("test_qil006_")
    executor = MigrationExecutor(connection)
    latest = executor.loader.graph.leaf_nodes()
    previous = [node for node in latest if node[0] != "learning"] + [("learning", "0002_topic_revision")]
    # Earlier legacy migration tests may stop at their own historical target.
    # Restore the complete graph before planning a backwards-only transition.
    executor.migrate(latest)
    executor = MigrationExecutor(connection)
    executor.migrate(previous)
    try:
        old = MigrationExecutor(connection).loader.project_state(previous).apps
        Topic = old.get_model("learning", "Topic")
        Translation = old.get_model("learning", "TopicTranslation")
        published = Topic.objects.create(status="published", revision=17)
        draft = Topic.objects.create(status="draft", revision=9)
        for language in ("ru", "en"):
            Translation.objects.create(topic=published, language=language, title=f" {language} title\n", article_body=f"\n  {language} original\r\n\n")
        Translation.objects.create(topic=draft, language="ru", title="", article_body="\n")
        User = old.get_model("accounts", "User")
        user = User.objects.create(email="sections-migration@example.invalid", password="!")
        old.get_model("assessments", "TopicProgress").objects.create(user_id=user.pk, topic_id=published.pk)
        for submitted in (False, True):
            old.get_model("assessments", "Attempt").objects.create(
                user_id=user.pk, topic_id=published.pk, content_snapshot={"historical": ["unchanged", {"ru": "text", "en": "text"}]},
                **({"status": "submitted", "submitted_at": timezone.now(), "submitted_language": "en",
                    "submitted_answers": [{"question_id": "1", "choice_ids": ["2"]}], "correct_count": 1, "total_count": 1} if submitted else {}),
            )
        config = old.get_model("practice", "TopicPractice").objects.create(topic_id=published.pk)
        task = old.get_model("practice", "PracticeTask").objects.create(topic_practice_id=config.pk)
        old.get_model("practice", "PracticeSubmission").objects.create(user_id=user.pk, task_id=task.pk, task_snapshot={"historical": "practice"})
        old.get_model("assessments", "UserProgressState").objects.create(user_id=user.pk, generation=4)
        tracked = [("learning", "Topic"), ("learning", "TopicTranslation"), ("accounts", "User"),
                   ("assessments", "Attempt"), ("assessments", "TopicProgress"), ("assessments", "UserProgressState"),
                   ("practice", "PracticeTask"), ("practice", "PracticeSubmission")]
        before = {key: list(old.get_model(*key).objects.order_by("pk").values()) for key in tracked}
        MigrationExecutor(connection).migrate(latest)
        new = MigrationExecutor(connection).loader.project_state(latest).apps
        assert before == {key: list(new.get_model(*key).objects.order_by("pk").values()) for key in tracked}
        Section = new.get_model("learning", "TopicSection")
        SectionTranslation = new.get_model("learning", "TopicSectionTranslation")
        assert Section.objects.count() == 2 and SectionTranslation.objects.count() == 3
        for topic in Topic.objects.all():
            section = Section.objects.get(topic_id=topic.pk)
            assert (section.position, section.status) == (10, topic.status)
            assert list(SectionTranslation.objects.filter(section_id=section.pk).order_by("language").values_list("language", "title", "article_body")) == list(
                Translation.objects.filter(topic_id=topic.pk).order_by("language").values_list("language", "title", "article_body"))
    finally:
        MigrationExecutor(connection).migrate(latest)


@pytest.mark.django_db(transaction=True)
def test_migration_refuses_corrupt_published_article_without_partial_copy():
    assert connection.settings_dict["NAME"].startswith("test_qil006_")
    executor = MigrationExecutor(connection)
    latest = executor.loader.graph.leaf_nodes()
    previous = [node for node in latest if node[0] != "learning"] + [("learning", "0002_topic_revision")]
    executor.migrate(latest)
    executor = MigrationExecutor(connection)
    executor.migrate(previous)
    old = MigrationExecutor(connection).loader.project_state(previous).apps
    Topic = old.get_model("learning", "Topic")
    try:
        Topic.objects.create(status="draft")
        corrupt = Topic.objects.create(status="published")
        with pytest.raises(RuntimeError, match="migration rolled back"):
            MigrationExecutor(connection).migrate(latest)
        assert "learning_topicsection" not in connection.introspection.table_names()
        assert Topic.objects.count() == 2
        Topic.objects.filter(pk=corrupt.pk).update(status="draft")
    finally:
        Topic.objects.filter(status="published").update(status="draft")
        MigrationExecutor(connection).migrate(latest)
