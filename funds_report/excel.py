"""xlsx report rendering. Two-column side-by-side layout, themed per manager."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .config import Fund
from .metrics import FundReport

MSK = timezone(timedelta(hours=3))

THEME_BLUE = {"fill": "184EA1", "fund_color": "184EA1", "fund_fill": "E8EEF7"}
THEME_GREEN = {"fill": "1F8468", "fund_color": "1F8468", "fund_fill": "E6F2EC"}

POS_COLOR = "1F8468"
NEG_COLOR = "C0392B"
FLAG_COLOR = "B45309"  # amber: anomaly highlight (cell font, not background)
NEUTRAL_GRAY = "6C757D"
BORDER_COLOR = "C0C0C0"


def _border() -> Border:
    side = Side(style="thin", color=BORDER_COLOR)
    return Border(left=side, right=side, top=side, bottom=side)


def _fmt_nav(d: Decimal) -> float:
    """Excel handles Decimals oddly; convert just at the edge for display."""
    return float(d)


def _render_block(ws, fund: Fund, report: FundReport, start_row: int,
                  col_offset: int, theme: dict) -> int:
    border = _border()
    fund_fill = PatternFill("solid", fgColor=theme["fund_fill"])
    fund_label_font = Font(bold=True, size=12, color=theme["fund_color"])
    base_label_font = Font(bold=True, size=10, color=theme["fund_color"], italic=True)
    pos_font = Font(color=POS_COLOR, bold=True)
    neg_font = Font(color=NEG_COLOR, bold=True)
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)

    c0, c1, c2, c3, c4 = (col_offset + i for i in range(5))

    # Fund header — name + base date/value, two lines, single tall row
    ws.merge_cells(start_row=start_row, start_column=c0, end_row=start_row, end_column=c4)
    base_str = (f"база {report.baseline_date.strftime('%d.%m.%Y')}: "
                f"{_fmt_nav(report.baseline_nav):,.4f} ₽").replace(",", " ")
    cell = ws.cell(row=start_row, column=c0,
                   value=f"{fund.name} ({fund.code}) — {fund.kind}\n{base_str}")
    cell.font = fund_label_font
    cell.fill = fund_fill
    cell.alignment = center
    ws.row_dimensions[start_row].height = 38
    row = start_row + 1

    # Per-day deltas
    for d in report.deltas:
        d_font = pos_font if d.delta_pct >= 0 else neg_font
        c_font = pos_font if d.cumulative_pct >= 0 else neg_font
        if d.flagged:
            d_font = Font(color=FLAG_COLOR, bold=True)
        cells = [
            (c0, d.date.strftime("%d.%m.%Y"), None, None),
            (c1, _fmt_nav(d.nav), "#,##0.0000", None),
            (c2, float(d.delta_pct) / 100, "+0.0000%;-0.0000%;0.0000%", d_font),
            (c3, float(d.cumulative_pct) / 100, "+0.0000%;-0.0000%;0.0000%", c_font),
            (c4, "⚠ аномалия" if d.flagged else "", None,
             Font(color=FLAG_COLOR, italic=True) if d.flagged else None),
        ]
        for col, val, fmt, fnt in cells:
            cell = ws.cell(row=row, column=col, value=val)
            if fmt: cell.number_format = fmt
            if fnt: cell.font = fnt
            cell.alignment = center
            cell.border = border
        row += 1

    # Total row — bold, themed background, only the cumulative-% cell carries a value
    total_font = pos_font if report.total_pct >= 0 else neg_font
    total_cells = [
        (c0, "ИТОГО", None, base_label_font),
        (c1, "", None, None),
        (c2, "", None, None),
        (c3, float(report.total_pct) / 100, "+0.0000%;-0.0000%;0.0000%", total_font),
        (c4, "", None, None),
    ]
    for col, val, fmt, fnt in total_cells:
        cell = ws.cell(row=row, column=col, value=val)
        if fmt: cell.number_format = fmt
        if fnt: cell.font = fnt
        cell.alignment = center
        cell.border = border
        cell.fill = fund_fill
    row += 1

    # Per-fund warnings (e.g. stale data) under the block, italic gray, full-width
    for w in report.warnings:
        ws.merge_cells(start_row=row, start_column=c0, end_row=row, end_column=c4)
        cell = ws.cell(row=row, column=c0, value=f"⚠ {w}")
        cell.font = Font(italic=True, size=9, color=FLAG_COLOR)
        cell.alignment = Alignment(horizontal="center", vertical="center")
        row += 1

    return row


def build_xlsx(left: list[tuple[Fund, FundReport]],
               right: list[tuple[Fund, FundReport]],
               period_label: str,
               out_path: Path) -> None:
    """Write the side-by-side report. left = wealthim (blue), right = first-am (green)."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Сводка"

    border = _border()

    # Title — full width, blue, large
    ws.merge_cells("A1:K1")
    cell = ws["A1"]
    cell.value = f"Отчёт по стоимости пая — {period_label}"
    cell.font = Font(bold=True, size=14, color=THEME_BLUE["fill"])
    cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 28

    # Timestamp subtitle
    ws.merge_cells("A2:K2")
    cell = ws["A2"]
    cell.value = f"Сформировано: {datetime.now(MSK).strftime('%d.%m.%Y %H:%M')} МСК"
    cell.font = Font(italic=True, size=10, color=NEUTRAL_GRAY)
    cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[2].height = 16

    # Manager headers (row 3) — colored solid bars
    manager_font = Font(bold=True, color="FFFFFF", size=13)
    for cells_range, text, theme in [
        ("A3:E3", "УК «ВИМ Инвестиции» — wealthim.ru", THEME_BLUE),
        ("G3:K3", "УК «Первая» — first-am.ru", THEME_GREEN),
    ]:
        ws.merge_cells(cells_range)
        cell = ws[cells_range.split(":")[0]]
        cell.value = text
        cell.font = manager_font
        cell.fill = PatternFill("solid", fgColor=theme["fill"])
        cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[3].height = 24

    # Column headers (row 5) — themed per side
    headers = ["Дата", "Стоимость пая, ₽", "Δ за день, %", "Δ нарастающим, %", "Прим."]
    header_font = Font(bold=True, color="FFFFFF", size=11)
    for side_col_offset, theme in [(1, THEME_BLUE), (7, THEME_GREEN)]:
        for i, h in enumerate(headers):
            cell = ws.cell(row=5, column=side_col_offset + i, value=h)
            cell.font = header_font
            cell.fill = PatternFill("solid", fgColor=theme["fill"])
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = border
    ws.row_dimensions[5].height = 32

    # Fund blocks, paired
    row = 6
    for i in range(max(len(left), len(right))):
        l_end = (_render_block(ws, *left[i], row, 1, THEME_BLUE)
                 if i < len(left) else row)
        r_end = (_render_block(ws, *right[i], row, 7, THEME_GREEN)
                 if i < len(right) else row)
        row = max(l_end, r_end) + 1  # gap between fund pairs

    # Column widths — F is the narrow separator
    for off in (0, 6):
        for i, w in enumerate([12, 18, 14, 18, 24]):
            ws.column_dimensions[get_column_letter(off + 1 + i)].width = w
    ws.column_dimensions["F"].width = 2

    wb.save(out_path)
