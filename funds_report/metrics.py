"""Delta computation, validation, anomaly detection. All Decimal-based."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, getcontext

from .config import Sanity

# Plenty of headroom for any realistic NAV math; we round only at presentation.
getcontext().prec = 28
HUNDRED = Decimal("100")
ONE = Decimal("1")


@dataclass(frozen=True)
class DayDelta:
    date: date
    nav: Decimal
    delta_pct: Decimal           # percent change vs previous trading day in tail
    cumulative_pct: Decimal      # compounded since baseline
    flagged: bool = False        # set when |delta_pct| exceeds threshold


@dataclass(frozen=True)
class FundReport:
    baseline_date: date
    baseline_nav: Decimal
    deltas: list[DayDelta]
    total_pct: Decimal
    warnings: list[str] = field(default_factory=list)


def _pct(new: Decimal, old: Decimal) -> Decimal:
    if old == 0:
        raise ValueError("baseline NAV is zero — cannot compute %")
    return (new - old) / old * HUNDRED


def compute_report(history: list[tuple[date, Decimal]], n_days: int, sanity: Sanity) -> FundReport:
    """Compute deltas + cumulative + sanity checks. Cross-validates total two ways.

    Raises ValueError on structurally bad input (too short, stale, NAV<=0, etc.).
    Mild anomalies become flags/warnings, not errors.
    """
    if len(history) < 2:
        raise ValueError(f"history too short: {len(history)} rows")
    for d, v in history:
        if v <= 0:
            raise ValueError(f"non-positive NAV at {d}: {v}")

    latest_date = history[-1][0]
    today = datetime.now().date()
    age = (today - latest_date).days
    warnings: list[str] = []
    if age > sanity.max_staleness_days:
        warnings.append(
            f"данные устарели: последняя точка {latest_date.strftime('%d.%m.%Y')} "
            f"({age} календарных дней назад)"
        )

    if len(history) < n_days + 1:
        raise ValueError(f"not enough history for {n_days}-day report "
                         f"(need {n_days + 1} rows, have {len(history)})")
    tail = history[-(n_days + 1):]

    baseline_date, baseline_nav = tail[0]
    threshold = sanity.flag_daily_pct_above
    deltas: list[DayDelta] = []
    cum_factor = ONE  # multiplicative compounding for cumulative %
    for i in range(1, len(tail)):
        prev_v = tail[i - 1][1]
        cur_d, cur_v = tail[i]
        d_pct = _pct(cur_v, prev_v)
        cum_factor *= (ONE + d_pct / HUNDRED)
        cum_pct = (cum_factor - ONE) * HUNDRED
        deltas.append(DayDelta(
            date=cur_d, nav=cur_v,
            delta_pct=d_pct, cumulative_pct=cum_pct,
            flagged=abs(d_pct) >= threshold,
        ))

    # Two independent computations of "total since baseline":
    # (a) compounded factor from per-day Δ (cum_factor)
    # (b) direct ratio latest/baseline
    total_pct_direct = _pct(tail[-1][1], baseline_nav)
    total_pct_compound = (cum_factor - ONE) * HUNDRED
    if abs(total_pct_direct - total_pct_compound) > sanity.cross_validate_tolerance_pct:
        raise ValueError(
            f"cross-validation failed: direct={total_pct_direct} compound={total_pct_compound}"
        )

    # Use the direct value (no accumulated rounding) for the headline total.
    return FundReport(
        baseline_date=baseline_date,
        baseline_nav=baseline_nav,
        deltas=deltas,
        total_pct=total_pct_direct,
        warnings=warnings,
    )


# Russian grammar helpers — small enough to live with the metrics they label.
WEEKDAYS_GEN = ["понедельника", "вторника", "среды", "четверга",
                "пятницы", "субботы", "воскресенья"]
WEEKDAYS_ACC = ["понедельник", "вторник", "среду", "четверг",
                "пятницу", "субботу", "воскресенье"]


def plural_days(n: int) -> str:
    """1 торг. день / 2-4 торг. дня / 5+ торг. дней (handles teens correctly)."""
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} торг. день"
    if 2 <= n % 10 <= 4 and not (12 <= n % 100 <= 14):
        return f"{n} торг. дня"
    return f"{n} торг. дней"


def period_label(reports: list[FundReport]) -> str:
    """'с четверга 24.04.2026 по четверг 30.04.2026 (4 торг. дня)' — derived from data, not args."""
    baselines = [r.baseline_date for r in reports]
    latests = [r.deltas[-1].date for r in reports]
    d_from, d_to = min(baselines), max(latests)
    n_days = max(len(r.deltas) for r in reports)
    return (f"с {WEEKDAYS_GEN[d_from.weekday()]} {d_from.strftime('%d.%m.%Y')} "
            f"по {WEEKDAYS_ACC[d_to.weekday()]} {d_to.strftime('%d.%m.%Y')} "
            f"({plural_days(n_days)})")
