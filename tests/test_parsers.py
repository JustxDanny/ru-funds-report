"""Pure-function parser tests — no network, no clock."""

from __future__ import annotations

import io
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from openpyxl import Workbook

from funds_report.parsers import (
    extract_wealthim_export_params,
    parse_firstam_chart,
    parse_wealthim_xlsx,
)

FIXTURES = Path(__file__).parent / "fixtures"


# ── first-am chartData ────────────────────────────────────────────────────────

FIRSTAM_HTML = """
<html><body>
<script>
var chartData = [
  {"dateFormat":"24.04.2026","price":111.4500,"net_assets":12000000},
  {"dateFormat":"23.04.2026","price":112.0234,"net_assets":11900000},
  {"dateFormat":"27.04.2026","price":111.3601,"net_assets":12100000},
  {"dateFormat":"24.04.2026","price":111.4500,"net_assets":99}
];
</script>
</body></html>
"""


def test_firstam_chart_parses_decimals_and_dedupes_and_sorts():
    rows = parse_firstam_chart(FIRSTAM_HTML)
    # Three unique dates, ascending
    assert len(rows) == 3
    assert [d for d, _ in rows] == [date(2026, 4, 23), date(2026, 4, 24), date(2026, 4, 27)]
    # Decimal preserved exactly — no float-to-Decimal contamination
    assert rows[0][1] == Decimal("112.0234")
    assert rows[1][1] == Decimal("111.4500")
    assert rows[2][1] == Decimal("111.3601")


def test_firstam_chart_missing_raises():
    with pytest.raises(ValueError, match="chartData not found"):
        parse_firstam_chart("<html>nothing here</html>")


# ── wealthim form extraction ──────────────────────────────────────────────────

def test_extract_wealthim_export_params_returns_fond_id():
    html = (FIXTURES / "wealthim_form.html").read_text(encoding="utf-8")
    fields = extract_wealthim_export_params(html)
    assert fields["FOND_ID"].isdigit()
    assert fields["QUOTES_IBLOCK_ID"].isdigit()
    assert fields["FONDS_IBLOCK_ID"].isdigit()


def test_extract_wealthim_export_params_no_form_raises():
    with pytest.raises(ValueError, match="export_xlsx form not found"):
        extract_wealthim_export_params("<html>no form here</html>")


# ── wealthim xlsx parsing — synthetic xlsx, no network ────────────────────────

def _build_synthetic_wealthim_xlsx() -> bytes:
    """Mimic the wealthim xlsx export structure: header rows, then DD.MM.YYYY rows."""
    wb = Workbook()
    ws = wb.active
    ws.append(["ОПИФ Тестовый", None, None, None, None, None])
    ws.append(["c 01.04.2026 по 30.04.2026", None, None, None, None, None])
    ws.append(["Дата", "Стоимость пая, руб.", "Изменение пая %",
               "СЧА, руб.", "Изменение СЧА %", "Кол-во паев"])
    ws.append(["29.04.2026", 111.4848, "0.06 %", 12000000, "0.5 %", 100000])
    ws.append(["28.04.2026", 111.4150, "0.04 %", 11940000, "0.3 %", 100000])
    ws.append(["27.04.2026", 111.3601, "-0.08 %", 11900000, "-0.1 %", 100000])
    ws.append(["плохая строка", "не число", None, None, None, None])  # robust to junk
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_parse_wealthim_xlsx_extracts_decimals_and_skips_junk():
    rows = parse_wealthim_xlsx(_build_synthetic_wealthim_xlsx())
    assert len(rows) == 3
    assert [d for d, _ in rows] == [date(2026, 4, 27), date(2026, 4, 28), date(2026, 4, 29)]
    assert rows[-1][1] == Decimal("111.4848")  # 4-decimal precision preserved
