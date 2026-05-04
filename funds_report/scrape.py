"""Network-level scraping. Combines HTTP fetch with parser dispatch."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from decimal import Decimal

import httpx

from .config import Fund
from .parsers import extract_wealthim_export_params, parse_firstam_chart, parse_wealthim_xlsx

log = logging.getLogger(__name__)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
WEALTHIM_XLSX_ENDPOINT = (
    "https://www.wealthim.ru/local/templates/new/components/articul/quotes/.default/xlsx.php"
)
HTTP_TIMEOUT = 30.0


class ScrapeError(Exception):
    """Raised when scraping fails for a specific fund. Caller decides how to surface."""


def _client() -> httpx.Client:
    return httpx.Client(
        timeout=HTTP_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": UA, "Accept-Language": "ru-RU,ru;q=0.9"},
    )


def _fetch_firstam(fund: Fund) -> list[tuple[date, Decimal]]:
    log.info("fetch firstam %s %s", fund.code, fund.url)
    with _client() as c:
        r = c.get(fund.url)
        r.raise_for_status()
    return parse_firstam_chart(r.text)


def _fetch_wealthim_xlsx(fund: Fund, days_back: int = 400) -> list[tuple[date, Decimal]]:
    log.info("fetch wealthim %s %s", fund.code, fund.url)
    with _client() as c:
        r = c.get(fund.url)
        r.raise_for_status()
        params = extract_wealthim_export_params(r.text)
        today = datetime.now().date()
        params["from"] = (today - timedelta(days=days_back)).strftime("%d.%m.%Y")
        params["to"] = today.strftime("%d.%m.%Y")
        params["SHOWALL_1"] = "1"
        log.debug("wealthim xlsx params: FOND_ID=%s", params.get("FOND_ID"))
        r2 = c.get(WEALTHIM_XLSX_ENDPOINT, params=params, timeout=60.0)
        r2.raise_for_status()
    return parse_wealthim_xlsx(r2.content)


_DISPATCH = {
    "firstam_chart": _fetch_firstam,
    "wealthim_xlsx": _fetch_wealthim_xlsx,
}


def fetch_history(fund: Fund) -> list[tuple[date, Decimal]]:
    """Return full NAV history for a fund, ascending by date.

    Raises ScrapeError on any failure — callers catch and decide whether to abort
    the whole report or continue with a placeholder.
    """
    handler = _DISPATCH.get(fund.parser)
    if handler is None:
        raise ScrapeError(f"unknown parser {fund.parser!r} for {fund.code}")
    try:
        rows = handler(fund)
    except httpx.HTTPError as e:
        raise ScrapeError(f"{fund.code}: HTTP error: {e}") from e
    except Exception as e:
        raise ScrapeError(f"{fund.code}: parse error: {e}") from e
    if not rows:
        raise ScrapeError(f"{fund.code}: zero NAV rows parsed")
    return rows
