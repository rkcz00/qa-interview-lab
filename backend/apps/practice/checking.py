"""Versioned string comparison. No interpreter, SQL execution or network access."""

from django.db import models


ANSWER_MAX_LENGTH = 5000


class NormalizationMode(models.TextChoices):
    LF_TRIM_OUTER_V1 = "lf_trim_outer_v1", "LF + внешние пробелы/LF"
    LF_EXACT_V1 = "lf_exact_v1", "Только LF"


class Verdict(models.TextChoices):
    CORRECT = "correct", "Верно"
    INCORRECT = "incorrect", "Неверно"


class InvalidAnswer(ValueError):
    """The public answer is structurally invalid; never include its value."""


def validate_answer_text(value):
    if not isinstance(value, str):
        raise InvalidAnswer("Expected a string.")
    if len(value) > ANSWER_MAX_LENGTH:
        raise InvalidAnswer("Answer exceeds the character limit.")
    if any(char == "\0" or 0xD800 <= ord(char) <= 0xDFFF for char in value):
        raise InvalidAnswer("Invalid Unicode text.")
    return value


def normalize_answer(value, mode):
    validate_answer_text(value)
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    if mode == NormalizationMode.LF_TRIM_OUTER_V1:
        return normalized.strip(" \n")
    if mode == NormalizationMode.LF_EXACT_V1:
        return normalized
    # A corrupt/unsupported stored policy is a server error, not invalid learner data.
    raise ValueError("Unsupported normalization version.")


def verdict_for(normalized_answer, expected_answer):
    if normalized_answer == "" and expected_answer != "":
        raise InvalidAnswer("An empty answer is not allowed for this task.")
    return Verdict.CORRECT if normalized_answer == expected_answer else Verdict.INCORRECT
