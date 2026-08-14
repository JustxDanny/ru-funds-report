"""Enumerate every fund on wealthim.ru + first-am.ru, rank by 1-year return.

Run when picking funds for funds.yaml, or any time you want to re-rank
(e.g. quarterly to refresh the production set). Saves results to discovery.json.
"""

from __future__ import annotations

import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from funds_report.config import Fund  # noqa: E402
from funds_report.scrape import fetch_history, ScrapeError  # noqa: E402

WEALTHIM_LIST = "https://www.wealthim.ru/products/pif/"
FIRSTAM_HOME = "https://www.first-am.ru/"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"


def _fetch(url: str) -> str:
    with httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": UA}) as c:
        r = c.get(url)
        r.raise_for_status()
        return r.text


def list_wealthim_funds() -> list[Fund]:
    html = _fetch(WEALTHIM_LIST)
    out: list[Fund] = []
    seen: set[str] = set()
    for m in re.finditer(
        r'href="(/products/(pif/opif|bpif)/([a-z0-9_-]+)/)"[^>]*>([^<]{2,120})</a>', html
    ):
        href, kind, code, name = m.group(1), m.group(2), m.group(3), m.group(4).strip()
        name = re.sub(r"\s+", " ", name)
        if code in seen or not name or "Подробнее" in name or "Доходность" in name:
            continue
        seen.add(code)
        out.append(Fund(
            code=code.upper(), name=name,
            kind="ОПИФ" if "opif" in kind else "БПИФ",
            manager="ВИМ Инвестиции", parser="wealthim_xlsx",
            url=f"https://www.wealthim.ru{href}",
        ))
    return out


def list_firstam_funds() -> list[Fund]:
    html = _fetch(FIRSTAM_HOME)
    out: list[Fund] = []
    seen: set[str] = set()
    for kind, prefix in [("ОПИФ", "/individuals/fund/"), ("БПИФ", "/individuals/etf/")]:
        for m in re.finditer(
            rf'href="({re.escape(prefix)}([a-z0-9_-]+))"[^>]*>([^<]{{2,160}})</a>', html
        ):
            href, slug, name = m.group(1), m.group(2), m.group(3).strip()
            name = re.sub(r"\s+", " ", name)
            if slug in seen or not name or len(name) > 100:
                continue
            seen.add(slug)
            out.append(Fund(
                code=slug.upper(), name=name, kind=kind,
                manager="Первая", parser="firstam_chart",
                url=f"https://www.first-am.ru{href}",
            ))
    return out


def annual_return(history: list[tuple[date, float]], days_back: int = 365):
    """% over ~365 calendar days. Uses nearest row to target within ±30 days."""
    if len(history) < 2:
        return None
    latest_d, latest_v = history[-1]
    target = latest_d - timedelta(days=days_back)
    best_d, best_v, best_diff = None, None, 9999
    for d, v in history:
        diff = abs((d - target).days)
        if diff < best_diff:
            best_d, best_v, best_diff = d, v, diff
    if best_diff > 30:
        return None
    pct = (latest_v - best_v) / best_v * 100
    return {"pct_1y": float(pct),
            "latest_d": latest_d.strftime("%d.%m.%Y"), "latest_v": float(latest_v),
            "base_d": best_d.strftime("%d.%m.%Y"), "base_v": float(best_v)}


def process(fund: Fund) -> dict:
    base = {"code": fund.code, "name": fund.name, "manager": fund.manager,
            "kind": fund.kind, "url": fund.url, "parser": fund.parser}
    try:
        history = fetch_history(fund)
        ar = annual_return(history)
        if ar is None:
            return {**base, "error": "no 1y baseline", "rows": len(history)}
        return {**base, **ar, "rows": len(history)}
    except ScrapeError as e:
        return {**base, "error": str(e)}
    except Exception as e:
        return {**base, "error": f"{type(e).__name__}: {e}"}


def show_top(label: str, results: list[dict]) -> None:
    print(f"\n=== TOP 5 — {label} (по доходности за 1 год) ===")
    scored = sorted([r for r in results if "pct_1y" in r],
                    key=lambda x: x["pct_1y"], reverse=True)
    for i, r in enumerate(scored[:10], 1):
        mark = "★" if i <= 5 else " "
        print(f"  {mark} {i:2d}. {r['pct_1y']:+7.2f}%  {r['code']:25s}  {r['name'][:55]}")
        print(f"        {r['base_d']} {r['base_v']:.4f}  →  {r['latest_d']} {r['latest_v']:.4f}  "
              f"({r['rows']} rows)")
    errored = [r for r in results if "error" in r]
    if errored:
        print(f"  [errors: {len(errored)}]")
        for r in errored[:5]:
            print(f"     {r['code']:20s}  {r['error']}")


def main() -> int:
    print("[step] enumerating funds…")
    wim = list_wealthim_funds()
    fa = list_firstam_funds()
    print(f"  wealthim.ru: {len(wim)} funds")
    print(f"  first-am.ru: {len(fa)} funds")

    all_funds = wim + fa
    print(f"[step] fetching {len(all_funds)} fund histories (8 workers)…")
    t0 = time.time()
    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        for fut in as_completed(ex.submit(process, f) for f in all_funds):
            results.append(fut.result())
    print(f"  done in {time.time() - t0:.1f}s")

    show_top("wealthim.ru", [r for r in results if r["manager"] == "ВИМ Инвестиции"])
    show_top("first-am.ru", [r for r in results if r["manager"] == "Первая"])

    out = ROOT / "data" / "discovery.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str),
                   encoding="utf-8")
    print(f"\n[saved] {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
