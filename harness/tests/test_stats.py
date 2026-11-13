import math

import pytest

from analysis.stats import bootstrap_diff, bootstrap_mean, holm, mcnemar


def test_mcnemar_exact() -> None:
    # 10 discordant pairs, all favouring A: p = 2 * 0.5**10.
    a = [True] * 10 + [True] * 5
    b = [False] * 10 + [True] * 5
    r = mcnemar(a, b)
    assert (r.b, r.c) == (10, 0)
    assert r.p_value == pytest.approx(2 / 1024)


def test_mcnemar_no_discordance() -> None:
    assert mcnemar([True, False], [True, False]).p_value == 1.0


def test_mcnemar_balanced_is_one() -> None:
    assert mcnemar([True, False] * 3, [False, True] * 3).p_value == 1.0


def test_mcnemar_length_mismatch() -> None:
    with pytest.raises(ValueError):
        mcnemar([True], [True, False])


def test_bootstrap_is_seeded_and_brackets_mean() -> None:
    values = [1.0] * 18 + [0.0] * 12
    a = bootstrap_mean(values, resamples=2000)
    b = bootstrap_mean(values, resamples=2000)
    assert a == b
    assert a.estimate == pytest.approx(0.6)
    assert a.low < a.estimate < a.high
    assert a.low > 0.35 and a.high < 0.85


def test_bootstrap_constant_and_empty() -> None:
    c = bootstrap_mean([1.0] * 10, resamples=500)
    assert c.low == c.high == 1.0
    assert math.isnan(bootstrap_mean([]).estimate)


def test_bootstrap_diff_paired() -> None:
    a = [1.0] * 20 + [0.0] * 10
    b = [1.0] * 10 + [0.0] * 20
    d = bootstrap_diff(a, b, resamples=2000)
    assert d.estimate == pytest.approx(1 / 3)
    assert d.low > 0


def test_holm() -> None:
    # Classic example: sorted p = .01, .02, .03 -> .03, .04, .04
    assert holm([0.03, 0.01, 0.02]) == pytest.approx([0.04, 0.03, 0.04])
    assert holm([0.5, 0.9]) == pytest.approx([1.0, 1.0])
    assert holm([]) == []


def test_fisher_exact() -> None:
    from analysis.stats import fisher_exact

    # Tea-tasting table [[3, 1], [1, 3]]: two-sided p = 0.4857.
    assert fisher_exact(3, 4, 1, 4) == pytest.approx(0.4857, abs=1e-4)
    assert fisher_exact(5, 5, 0, 5) == pytest.approx(0.00794, abs=1e-4)
    assert fisher_exact(2, 4, 2, 4) == pytest.approx(1.0)
    with pytest.raises(ValueError):
        fisher_exact(5, 4, 0, 4)
