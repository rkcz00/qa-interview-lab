"""The optional demo loader is additive, atomic and never publishes automatically."""

from copy import deepcopy
import os
from pathlib import Path
import subprocess
import sys

import pytest
from django.core.exceptions import ValidationError
from django.db import connection

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from tools import load_demo_content as seed
from apps.accounts.models import User
from apps.learning.models import Language, Topic, TopicStatus, TopicTranslation


pytestmark = pytest.mark.django_db


def test_demo_seed_is_complete_bilingual_draft_and_preserves_existing_data():
    existing = Topic.objects.create()
    learner = User.objects.create_user("demo-existing@example.invalid")
    topic = seed.create_demo_content(connection.settings_dict["NAME"], confirmed=True)
    topic.validate_for_publication()
    assert topic.status == TopicStatus.DRAFT and topic.revision == 2
    assert set(topic.translations.values_list("language", flat=True)) == set(Language.values)
    assert list(topic.questions.values_list("question_type", flat=True)) == ["single_choice", "multiple_choice"]
    assert topic.terms.count() == 3
    assert sum(question.choices.count() for question in topic.questions.all()) == 8
    existing.refresh_from_db()
    assert (existing.status, existing.revision) == (TopicStatus.DRAFT, 1)
    assert User.objects.count() == 1 and User.objects.get().pk == learner.pk


@pytest.mark.parametrize("confirmed,matching_database", [(False, True), (True, False)])
def test_demo_seed_requires_confirmation_and_exact_database(confirmed, matching_database):
    name = connection.settings_dict["NAME"] if matching_database else "unused_demo_database"
    with pytest.raises(seed.DemoContentError):
        seed.create_demo_content(name, confirmed=confirmed)
    assert not Topic.objects.exists()


def test_demo_seed_duplicate_is_rejected_without_overwriting():
    topic = seed.create_demo_content(connection.settings_dict["NAME"], confirmed=True)
    before = list(TopicTranslation.objects.values_list("pk", "title", "article_body"))
    with pytest.raises(seed.DemoContentError):
        seed.create_demo_content(connection.settings_dict["NAME"], confirmed=True)
    assert Topic.objects.count() == 1
    assert list(TopicTranslation.objects.values_list("pk", "title", "article_body")) == before
    topic.refresh_from_db()
    assert topic.revision == 2


def test_demo_seed_incomplete_translation_rolls_back_entire_tree(monkeypatch):
    data = deepcopy(seed.demo_data())
    del data["questions"][-1]["choices"][-1]["translations"]["en"]
    monkeypatch.setattr(seed, "demo_data", lambda: data)
    with pytest.raises(ValidationError):
        seed.create_demo_content(connection.settings_dict["NAME"], confirmed=True)
    assert not Topic.objects.exists()
    assert not TopicTranslation.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_documented_demo_cli_creates_once_and_rejects_a_second_load():
    name = connection.settings_dict["NAME"]
    env = dict(os.environ, POSTGRES_DB=name, POSTGRES_TEST_DB="unused_demo_cli", PYTHONDONTWRITEBYTECODE="1")
    command = [sys.executable, "-B", str(seed.ROOT / "tools/load_demo_content.py"),
        "--database", name, "--confirm-create"]
    first = subprocess.run(command, cwd=seed.ROOT, env=env, capture_output=True, timeout=30)
    assert first.returncode == 0
    assert first.stdout.startswith(b"DEMO=PASS") and not first.stderr
    assert Topic.objects.count() == 1 and Topic.objects.get().status == TopicStatus.DRAFT
    second = subprocess.run(command, cwd=seed.ROOT, env=env, capture_output=True, timeout=30)
    assert second.returncode == 1
    assert second.stdout.startswith(b"DEMO=FAIL") and not second.stderr
    assert Topic.objects.count() == 1
