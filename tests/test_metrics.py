"""Tests for delta computation, anomaly flagging, cross-validation."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from funds_report.config import Sanity
from funds_report.metrics import compute_report, period_label, plural_days


SANITY = Sanity(
    flag_daily_pct_above=Decimal("3.0"),
    max_staleness_days=7,
    cross_validate_tolerance_pct=Decimal("0.0001"),
)

# Build a history that ends today so staleness warnings don't fire in unrelated tests.
TODAY = datetime.now().date()


def _hist(values: list[Decimal]) -> list[tuple[date, Decimal]]:
    """Pair successive values with successive trading dates ending today."""
    return [(TODAY - timedelta(days=len(values) - 1 - i), v) for i, v in enumerate(values)]


def test_compute_report_basic_4_day_window():
    history = _hist([
        Decimal("100.0000"),  # baseline (5 days ago)
        Decimal("100.5000"),  # +0.5%
        Decimal("100.0000"),  # -0.4975...%
        Decimal("101.0000"),  # +1.0%
        Decimal("101.5000"),  # +0.4950...%
    ])
    rep = compute_report(history, n_days=4, sanity=SANITY)
    assert rep.baseline_nav == Decimal("100.0000")
    assert len(rep.deltas) == 4
    # Direct total: (101.5 - 100) / 100 * 100 = 1.5%
    assert rep.total_pct == Decimal("1.5")
    # First daily delta: 0.5%
    assert rep.deltas[0].delta_pct == Decimal("0.5")
    # Cumulative on last day matches direct total within tolerance
    diff = abs(rep.deltas[-1].cumulative_pct - rep.total_pct)
    assert diff <= SANITY.cross_validate_tolerance_pct


def test_compute_report_flags_large_daily_move():
    # 5% jump → flagged
    history = _hist([Decimal("100"), Decimal("100.5"), Decimal("105.5"), Decimal("105.5")])
    rep = compute_report(history, n_days=3, sanity=SANITY)
    assert rep.deltas[0].flagged is False  # 0.5%
    assert rep.deltas[1].flagged is True   # ~4.97%
    assert rep.deltas[2].flagged is False  # 0%


def test_compute_report_warns_on_stale_history():
    old_today = TODAY - timedelta(days=20)
    history = [(old_today + timedelta(days=i), Decimal("100") + i) for i in range(5)]
    rep = compute_report(history, n_days=4, sanity=SANITY)
    assert any("устарели" in w for w in rep.warnings)


def test_compute_report_rejects_non_positive_nav():
    history = _hist([Decimal("100"), Decimal("0"), Decimal("100")])
    with pytest.raises(ValueError, match="non-positive NAV"):
        compute_report(history, n_days=2, sanity=SANITY)


def test_compute_report_rejects_too_short_history():
    with pytest.raises(ValueError, match="history too short"):
        compute_report([(TODAY, Decimal("100"))], n_days=1, sanity=SANITY)


def test_compute_report_rejects_too_short_for_window():
    history = _hist([Decimal("100"), Decimal("101")])
    with pytest.raises(ValueError, match="not enough history"):
        compute_report(history, n_days=10, sanity=SANITY)


def test_period_label_russian_grammar():
    """Output should use genitive after 'с' and accusative after 'по', plural-correct."""
    history = _hist([Decimal("100"), Decimal("101"), Decimal("102"), Decimal("103"), Decimal("104")])
    rep = compute_report(history, n_days=4, sanity=SANITY)
    label = period_label([rep])
    assert " по " in label
    # Genitive forms end in -а/-ы/-я
    parts = label.split(" по ")
    weekday_word = parts[0].split(" ")[1]  # word AFTER the preposition
    assert weekday_word.endswith(("а", "ы", "я", "и", "е"))
    assert "торг. дн" in label


def test_period_label_uses_so_before_sreda():
    """Russian: preposition 'с' becomes 'со' before consonant cluster 'ср'."""
    from funds_report.metrics import DayDelta, FundReport, period_label
    wed = date(2026, 4, 22)         # Wednesday
    thu = date(2026, 4, 23)
    rep = FundReport(
        baseline_date=wed, baseline_nav=Decimal("100"),
        deltas=[DayDelta(date=thu, nav=Decimal("101"),
                         delta_pct=Decimal("1"), cumulative_pct=Decimal("1"))],
        total_pct=Decimal("1"),
    )
    label = period_label([rep])
    assert label.startswith("со среды"), f"expected 'со среды …', got: {label!r}"


@pytest.mark.parametrize("n,expected", [
    (1, "1 торг. день"),
    (2, "2 торг. дня"),
    (4, "4 торг. дня"),
    (5, "5 торг. дней"),
    (11, "11 торг. дней"),
    (12, "12 торг. дней"),
    (21, "21 торг. день"),
    (22, "22 торг. дня"),
    (25, "25 торг. дней"),
    (101, "101 торг. день"),
])
def test_plural_days(n, expected):
    assert plural_days(n) == expected
