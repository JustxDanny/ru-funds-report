"""Print chat_ids of every user/group that has messaged the bot.

Use after onboarding a new recipient — they /start the bot, you run this,
copy the printed chat_id into .env's TELEGRAM_CHAT_IDS.
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from funds_report.config import load_env  # noqa: E402


def main() -> int:
    env = load_env(ROOT / ".env")
    token = env.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("error: TELEGRAM_BOT_TOKEN missing from .env", file=sys.stderr)
        return 2

    r = httpx.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=15)
    body = r.json()
    if not body.get("ok"):
        print(f"telegram error: {body}", file=sys.stderr)
        return 1

    seen: dict[int, str] = {}
    for upd in body["result"]:
        msg = upd.get("message") or upd.get("edited_message") or {}
        chat = msg.get("chat")
        if not chat:
            continue
        cid = chat["id"]
        name = (chat.get("first_name", "") + " " + chat.get("last_name", "")).strip()
        seen[cid] = name or chat.get("title", "(group)")

    if not seen:
        print("No messages yet. Have the user open https://t.me/<your_bot> and tap Start.")
        return 0

    print("Recipients who have messaged the bot:")
    for cid, name in seen.items():
        print(f"  chat_id={cid}  name={name!r}")
    print()
    print(f"To send to all of them, set in .env:")
    print(f"  TELEGRAM_CHAT_IDS={','.join(str(c) for c in seen)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
