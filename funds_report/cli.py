"""CLI orchestration. Parses args, loads config, scrapes, builds xlsx, sends."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

from .config import Fund, load_config, load_env
from .excel import build_xlsx
from .metrics import FundReport, compute_report, period_label
from .notify import build_caption, send_document, TelegramError
from .scrape import ScrapeError, fetch_history

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "out"
MSK = timezone(timedelta(hours=3))

log = logging.getLogger("funds_report")


def determine_days(arg_days: int | None) -> int:
    """Mon → 3 trading days (prev week's Wed/Thu/Fri recap), Fri → 4 (current Mon-Thu)."""
    if arg_days is not None:
        return arg_days
    wd = datetime.now(MSK).weekday()
    return {0: 3, 4: 4}.get(wd, 5)


def collect(funds: list[Fund], n_days: int, sanity) -> list[tuple[Fund, FundReport]]:
    out: list[tuple[Fund, FundReport]] = []
    for fund in funds:
        history = fetch_history(fund)
        report = compute_report(history, n_days, sanity)
        out.append((fund, report))
        log.info("  %s: %d deltas, total=%+0.4f%%, warnings=%d",
                 fund.code, len(report.deltas), report.total_pct, len(report.warnings))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="funds-report",
                                 description="NAV report → xlsx → Telegram")
    ap.add_argument("--days", type=int, default=None,
                    help="trading days to compare (auto by weekday if omitted)")
    ap.add_argument("--no-send", action="store_true", help="build xlsx but do not send")
    ap.add_argument("--chat-id", default=None,
                    help="override TELEGRAM_CHAT_IDS — comma separated")
    ap.add_argument("--config", type=Path, default=ROOT / "data" / "funds.yaml")
    ap.add_argument("--env", type=Path, default=ROOT / ".env")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(
        # Stdout, not stderr — Task Scheduler / PowerShell wrap stderr lines as
        # NativeCommandError records, which breaks the wrapper script.
        stream=sys.stdout,
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # httpx logs the full request URL at INFO — and the Telegram URL carries the
    # bot token in its path. That would write the live token into logs/*.log on
    # every send. Keep it at WARNING; our own log lines say enough.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    cfg = load_config(args.config)
    env = load_env(args.env)
    by_mgr = cfg.by_manager()
    wealthim_funds = by_mgr.get("ВИМ Инвестиции", [])
    firstam_funds = by_mgr.get("Первая", [])
    if not wealthim_funds and not firstam_funds:
        log.error("no funds configured under known managers"); return 2

    n_days = determine_days(args.days)
    log.info("period: %d trading days", n_days)

    log.info("scraping wealthim.ru (%d funds)...", len(wealthim_funds))
    try:
        left = collect(wealthim_funds, n_days, cfg.sanity)
    except (ScrapeError, ValueError) as e:
        log.error("wealthim collection failed: %s", e); return 3

    log.info("scraping first-am.ru (%d funds)...", len(firstam_funds))
    try:
        right = collect(firstam_funds, n_days, cfg.sanity)
    except (ScrapeError, ValueError) as e:
        log.error("first-am collection failed: %s", e); return 3

    label = period_label([r for _, r in left + right])
    log.info("period label: %s", label)

    OUT_DIR.mkdir(exist_ok=True)
    ts = datetime.now(MSK).strftime("%Y-%m-%d_%H%M")
    out_path = OUT_DIR / f"funds_report_{ts}.xlsx"
    build_xlsx(left, right, label, out_path)
    log.info("xlsx written: %s", out_path)

    if args.no_send:
        return 0

    token = env.get("TELEGRAM_BOT_TOKEN")
    raw_ids = args.chat_id or env.get("TELEGRAM_CHAT_IDS") or env.get("TELEGRAM_CHAT_ID", "")
    chat_ids = [x.strip() for x in raw_ids.split(",") if x.strip()]
    if not token or not chat_ids:
        log.warning("token or chat ids missing — not sending"); return 0

    caption = build_caption(label, left, right)
    failures = 0
    for cid in chat_ids:
        try:
            res = send_document(token, cid, out_path, caption)
            log.info("sent to %s — message_id=%s", cid, res["result"]["message_id"])
        except TelegramError as e:
            log.error("send to %s failed: %s", cid, e); failures += 1

    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
