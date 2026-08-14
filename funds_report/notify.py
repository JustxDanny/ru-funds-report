"""Telegram delivery. One bot, N recipients. Plain text caption (HTML escapes the names)."""

from __future__ import annotations

import html
import logging
import re
from pathlib import Path

import httpx

from .config import Fund
from .metrics import FundReport

log = logging.getLogger(__name__)

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class TelegramError(RuntimeError):
    """Telegram API returned non-OK. Caller logs and continues with other recipients."""


_TG_TOKEN_URL = re.compile(r"(api\.telegram\.org/bot)[^/]+/", re.IGNORECASE)


def _redact(s: str, token: str) -> str:
    # Token sits in the URL path; any httpx error message echoing the URL would leak it
    # to logs/*.log (run_scheduled.ps1 redirects stderr → log file). Exact-match the raw
    # token, then also redact by URL shape — httpx may percent-encode the ':' (%3A), so
    # the raw match alone would miss it.
    if not token:
        return s
    s = s.replace(token, "[REDACTED_TOKEN]")
    return _TG_TOKEN_URL.sub(r"\1[REDACTED_TOKEN]/", s)


def send_document(token: str, chat_id: str, file_path: Path, caption: str,
                  timeout: float = 60.0) -> dict:
    url = f"https://api.telegram.org/bot{token}/sendDocument"
    try:
        with open(file_path, "rb") as f:
            files = {"document": (file_path.name, f, XLSX_MIME)}
            data = {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"}
            r = httpx.post(url, files=files, data=data, timeout=timeout)
    except httpx.HTTPError as e:
        raise TelegramError(f"transport: {_redact(str(e), token)}") from None
    try:
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    except ValueError:
        body = {}
    if r.status_code != 200 or not body.get("ok"):
        raise TelegramError(f"HTTP {r.status_code}: {_redact(str(body or r.text), token)}")
    return body


def build_caption(period_label: str,
                  left: list[tuple[Fund, FundReport]],
                  right: list[tuple[Fund, FundReport]]) -> str:
    """HTML-escaped caption with a per-fund total. Manager-grouped."""
    lines = [
        "<b>Отчёт по стоимости пая</b>",
        f"<i>{html.escape(period_label)}</i>",
        "",
        "<b>УК «ВИМ Инвестиции»:</b>",
    ]
    for fund, rep in left:
        sign = "+" if rep.total_pct >= 0 else ""
        lines.append(f"• {html.escape(fund.name)}: {sign}{rep.total_pct:.4f}%")
    lines.append("")
    lines.append("<b>УК «Первая»:</b>")
    for fund, rep in right:
        sign = "+" if rep.total_pct >= 0 else ""
        lines.append(f"• {html.escape(fund.name)}: {sign}{rep.total_pct:.4f}%")
    return "\n".join(lines)
