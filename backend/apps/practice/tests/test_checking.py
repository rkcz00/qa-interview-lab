import pytest

from apps.practice.checking import InvalidAnswer, NormalizationMode as Mode, Verdict, normalize_answer, verdict_for
from apps.practice.serializers import DeletePracticeSerializer, StartPracticeSerializer, SubmitPracticeSerializer


@pytest.mark.parametrize("mode", list(Mode.values))
@pytest.mark.parametrize("raw,lf", [
    ("a\r\nb\rc\n", "a\nb\nc\n"), ("\\n", "\\n"), ("\ttext\t", "\ttext\t"),
    ("\u00a0text\u00a0", "\u00a0text\u00a0"), ("Text!", "Text!"), ("é", "é"),
    ("e\u0301", "e\u0301"), (" \r\n  a b  \r ", " \n  a b  \n "),
], ids=["line-endings", "literal-backslash", "tabs", "nbsp", "case-punctuation", "composed", "decomposed", "outer"])
def test_versioned_normalization_is_minimal_and_idempotent(mode, raw, lf):
    expected = lf.strip(" \n") if mode == Mode.LF_TRIM_OUTER_V1 else lf
    assert normalize_answer(raw, mode) == expected
    assert normalize_answer(expected, mode) == expected


@pytest.mark.parametrize("raw", [None, 42, 1.5, True, [], {}, "a\0b", "\ud800", "\udfff", "x" * 5001],
                         ids=["null", "integer", "float", "boolean", "list", "object", "nul", "high-surrogate", "low-surrogate", "over-limit"])
def test_invalid_raw_answers_fail_before_normalization(raw):
    with pytest.raises(InvalidAnswer):
        normalize_answer(raw, Mode.LF_TRIM_OUTER_V1)


@pytest.mark.parametrize("size", [0, 4999, 5000])
def test_limit_counts_unicode_scalar_values(size):
    value = "😀" * size
    assert normalize_answer(value, Mode.LF_EXACT_V1) == value


def test_raw_limit_is_checked_before_trimming():
    with pytest.raises(InvalidAnswer):
        normalize_answer(" " * 5001, Mode.LF_TRIM_OUTER_V1)
    with pytest.raises(ValueError):
        normalize_answer("x", "unknown-version")


@pytest.mark.parametrize("actual,expected,verdict", [
    ("text", "text", Verdict.CORRECT), ("Text", "text", Verdict.INCORRECT),
    ("text\n", "text", Verdict.INCORRECT), ("", "", Verdict.CORRECT),
    ("x", "", Verdict.INCORRECT), ("\t", "", Verdict.INCORRECT),
], ids=["equal", "case", "newline", "empty-reference", "nonempty-vs-empty", "tab"])
def test_exact_comparison_has_only_a_verdict(actual, expected, verdict):
    assert verdict_for(actual, expected) == verdict


def test_empty_answer_against_nonempty_reference_is_invalid():
    with pytest.raises(InvalidAnswer):
        verdict_for("", "text")


@pytest.mark.parametrize("answer", [None, 42, True, [], {}, "\0", "\ud800", "x" * 5001],
                         ids=["null", "integer", "boolean", "list", "object", "nul", "surrogate", "too-long"])
def test_serializer_rejects_unsupported_json_answer_types(answer):
    assert not SubmitPracticeSerializer(data={"language": "ru", "answer_text": answer}).is_valid()


def test_requests_are_strict_and_empty_text_is_not_client_rejected():
    serializer = SubmitPracticeSerializer(data={"language": "en", "answer_text": ""})
    assert serializer.is_valid() and serializer.validated_data["answer_text"] == ""
    for payload in ({}, {"language": "ru"}, {"language": "ru", "answer_text": "x", "verdict": "correct"}):
        assert not SubmitPracticeSerializer(data=payload).is_valid()
    assert not StartPracticeSerializer(data={"language": "de"}).is_valid()
    assert DeletePracticeSerializer(data={}).is_valid()
    assert not DeletePracticeSerializer(data=[]).is_valid()


def test_explicit_response_serializers_exclude_snapshot_keys_and_saved_answers():
    from types import SimpleNamespace
    from apps.practice.serializers import PendingPracticeSerializer, SubmittedPracticeSerializer
    from django.utils import timezone

    row = SimpleNamespace(pk=1, task_id=2, status="in_progress", task_snapshot={
        "topic_id": "3", "practice_kind": "single_correct_answer", "source_type": "python",
        "source_text": "pass", "input_data": "", "environment": "Python", "output_spec": "stdout",
        "normalization_mode": "lf_exact_v1", "answer_max_length": 5000, "expected_answer": "private",
        "source_revision": 9, "translations": {"ru": {"title": "Задание", "prompt": "Условие", "expected_answer": "private"}},
    }, submitted_answer="private", submitted_language="ru", submitted_at=timezone.now(), verdict="correct")
    public = PendingPracticeSerializer(row, context={"language": "ru"}).data
    forbidden = {"expected_answer", "task_snapshot", "source_revision", "submitted_answer", "user_id"}
    assert not forbidden.intersection(public) and not forbidden.intersection(public["task"])
    row.status = "submitted"
    public = SubmittedPracticeSerializer(row).data
    assert not forbidden.intersection(public) and "task" not in public
    assert public["result"] == {"verdict": "correct"}


def test_admin_preserves_significant_reference_whitespace_before_versioned_preparation():
    from django.contrib import admin
    from apps.practice.models import PracticeTask
    model_admin = admin.site.get_model_admin(PracticeTask)
    for name in ("expected_answer", "source_text", "input_data"):
        field = model_admin.formfield_for_dbfield(PracticeTask._meta.get_field(name), None)
        assert field.clean("  value\n ") == "  value\n "
