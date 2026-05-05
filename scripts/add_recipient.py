"""Interactive: add a new Telegram chat_id to .env's TELEGRAM_CHAT_IDS.

Usage:
    python scripts/add_recipient.py

Walks you through:
  1. List everyone who has /start'd the bot (via getUpdates)
  2. Show who's already in .env
  3. Pick which new chat_id to add (or paste one manually)
  4. Update .env safely (in-place edit, preserves other keys + comments)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from funds_report.config import load_env  # noqa: E402

ENV_PATH = ROOT / ".env"


def fetch_recipients(token: str) -> dict[int, str]:
    r = httpx.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=15)
    body = r.json()
    if not body.get("ok"):
        raise SystemExit(f"telegram error: {body}")
    seen: dict[int, str] = {}
    for upd in body["result"]:
        msg = upd.get("message") or upd.get("edited_message") or {}
        chat = msg.get("chat")
        if not chat:
            continue
        cid = chat["id"]
        name = (chat.get("first_name", "") + " " + chat.get("last_name", "")).strip()
        seen[cid] = name or chat.get("title", "(group)")
    return seen


def update_env(new_ids: list[str]) -> None:
    """Rewrite .env with merged TELEGRAM_CHAT_IDS — no other lines touched."""
    text = ENV_PATH.read_text(encoding="utf-8")
    lines = text.splitlines()
    out: list[str] = []
    written = False
    for line in lines:
        if re.match(r"^\s*TELEGRAM_CHAT_IDS\s*=", line):
            out.append(f"TELEGRAM_CHAT_IDS={','.join(new_ids)}")
            written = True
        else:
            out.append(line)
    if not written:
        out.append(f"TELEGRAM_CHAT_IDS={','.join(new_ids)}")
    ENV_PATH.write_text("\n".join(out) + "\n", encoding="utf-8")


def main() -> int:
    env = load_env(ENV_PATH)
    token = env.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("error: TELEGRAM_BOT_TOKEN missing from .env")
        return 2

    current = [x.strip() for x in env.get("TELEGRAM_CHAT_IDS", "").split(",") if x.strip()]
    print(f"Current recipients in .env: {current or '(none)'}\n")

    print("Polling Telegram for everyone who has /start'd the bot...")
    seen = fetch_recipients(token)
    if not seen:
        print("  no messages found.")
        print("  → ask the new recipient to open https://t.me/DenchikAgentBot and tap Start, then re-run.")
        return 1

    print("\nFound:")
    options = list(seen.items())
    for i, (cid, name) in enumerate(options, 1):
        marker = "  (already added)" if str(cid) in current else ""
        print(f"  [{i}] chat_id={cid}  name={name!r}{marker}")

    print()
    sel = input("Pick a number to add (or paste a chat_id manually, or empty to cancel): ").strip()
    if not sel:
        print("cancelled.")
        return 0

    if sel.isdigit() and 1 <= int(sel) <= len(options):
        new_id = str(options[int(sel) - 1][0])
        new_name = options[int(sel) - 1][1]
    else:
        new_id = sel
        new_name = "(manual)"

    if new_id in current:
        print(f"chat_id {new_id} already in .env — nothing to do.")
        return 0

    merged = current + [new_id]
    update_env(merged)
    print(f"\nadded chat_id={new_id} ({new_name})")
    print(f".env now has TELEGRAM_CHAT_IDS={','.join(merged)}")
    print("\nNext run of the report sends to all of these. Test with:")
    print("  python -m funds_report --days 4")
    return 0


if __name__ == "__main__":
    sys.exit(main())
