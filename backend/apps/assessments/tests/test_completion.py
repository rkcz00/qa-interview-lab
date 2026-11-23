from fractions import Fraction

import pytest

from apps.assessments.completion import completion_value, rounded_percentage


@pytest.mark.parametrize("read,statuses,expected", [
    (False, (), 0), (True, (), 30),
    (False, ("unattempted",), 0), (True, ("failed",), 30),
    (False, ("passed",), 70), (True, ("passed",), 100),
    (False, ("passed", "unattempted"), 35),
    (True, ("passed", "unattempted"), 65),
    (True, ("failed", "passed"), 65),
    (True, ("failed", "failed"), 30),
    (True, ("passed", "passed"), 100),
])
def test_completion_weights_and_zero_activities(read, statuses, expected):
    assert completion_value(read, statuses) == expected


@pytest.mark.parametrize("value,expected", [(Fraction(25, 8), 3.13), (Fraction(100, 3), 33.33), (Fraction(200, 3), 66.67)])
def test_completion_rounds_half_up_without_float_thresholds(value, expected):
    assert rounded_percentage(value) == expected


def test_average_uses_exact_values_before_topic_rounding():
    first, second = Fraction(1, 6), Fraction()
    assert rounded_percentage((first + second) / 2) == 0.08
    assert rounded_percentage(first) == 0.17
    assert rounded_percentage(Fraction(65 + 100, 2)) == 82.5


@pytest.mark.parametrize("read,statuses", [(1, ()), (True, ("in_progress",)), (False, ("incorrect",))])
def test_completion_does_not_hide_invalid_domain_input(read, statuses):
    with pytest.raises(ValueError):
        completion_value(read, statuses)
