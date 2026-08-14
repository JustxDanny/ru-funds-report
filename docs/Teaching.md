# Teaching.md — How the Funds Report Was Built

> Audience: you (Daniel), with zero/light Python background. Pretend you're 15 and learning programming for the first time. We'll go from "what is Python" to "how every line in the script works", with no hand-waving.
>
> **A note on file paths.** This walkthrough was written before the
> hardening refactor. The logic shown is the same — the same parsers,
> the same delta math, the same xlsx building — but it now lives split
> across small files in `funds_report/` (`parsers.py`, `scrape.py`,
> `metrics.py`, `excel.py`, `notify.py`, `cli.py`). See `BUILDLOG.md`
> for what changed in the refactor and why. The code blocks below are
> still accurate as snippets; only the filenames moved.

---

## Part 0 — What we built (in one paragraph)

A small Python program that:
1. Visits two Russian fund-management websites (`wealthim.ru` and `first-am.ru`),
2. Reads the latest "стоимость пая" (NAV — net asset value) numbers from their public pages,
3. Calculates how much each of 10 hand-picked funds has gone up or down over the last few trading days,
4. Builds a nicely formatted Excel file with the results,
5. Sends that Excel file via Telegram to one or more people (currently you, soon your director).

It runs in ~10 seconds. No AI is involved at runtime. It costs zero rubles. And once we wire it to Windows Task Scheduler, it fires automatically every Monday and Friday morning.

---

## Part 1 — What is Python (and why we used it)

**Python** is a programming language. You write text files ending in `.py`, then a program called the **Python interpreter** (`python.exe` on Windows) reads that text and does what it says.

Why Python for this job?

| Need | Python tool |
|---|---|
| Download web pages | `httpx` library (modern HTTP client) |
| Find patterns in text (dates, numbers) | built-in `re` module (regex) |
| Parse JSON data | built-in `json` module |
| Make Excel files | `openpyxl` library |
| Talk to Telegram | `httpx` again — Telegram has a simple REST API |

Python's two superpowers that matter here:
- **Huge ecosystem of libraries.** Need to read Excel? `pip install openpyxl`. Need to call an API? `pip install httpx`. Someone's already done the hard work — you just import and use.
- **Reads like English.** `for fund in funds: print(fund["name"])` is almost a sentence.

---

## Part 2 — The big picture

Here's what happens when the script runs:

```
                 ┌──────────────────────┐
                 │  funds_report.py     │
                 └──────────┬───────────┘
                            │
       ┌────────────────────┼────────────────────┐
       │                    │                    │
       ▼                    ▼                    ▼
┌─────────────┐      ┌─────────────┐      ┌─────────────┐
│ wealthim.ru │      │ first-am.ru │      │ Telegram    │
│ (5 funds)   │      │ (5 funds)   │      │ Bot API     │
└──────┬──────┘      └──────┬──────┘      └──────▲──────┘
       │ HTML                │ HTML               │ POST
       │                     │                    │ xlsx
       ▼                     ▼                    │
   regex parse        find chartData JSON         │
       │                     │                    │
       └──────────┬──────────┘                    │
                  ▼                               │
       compute % deltas per day                   │
                  │                               │
                  ▼                               │
       build Excel with openpyxl                  │
                  │                               │
                  └───────────────────────────────┘
```

10 funds, 10 HTTP requests, 1 Excel file, 1 Telegram message. That's the whole show.

---

## Part 3 — Step-by-step walkthrough

### Step 3.1 — Downloading a webpage

The first thing the script does for each fund: ask the website for the page.

```python
import httpx

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"

def fetch(url: str) -> str:
    with httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": UA}) as c:
        r = c.get(url)
        r.raise_for_status()
        return r.text
```

What's happening line by line:

- `import httpx` — load the httpx library (we installed it earlier with `pip install httpx`).
- `UA = "Mozilla/..."` — a "User-Agent" string. It tells the website "I'm Chrome on Windows". Some sites refuse requests that don't claim to be a browser. We claim to be one.
- `def fetch(url: str) -> str:` — define a function called `fetch` that takes a URL (text) and returns text. The `: str` and `-> str` are **type hints** — optional, but they document what goes in/out.
- `with httpx.Client(...) as c:` — open an HTTP "session" called `c`. The `with` block makes sure the connection is closed when we're done, even if something errors.
- `timeout=30` — give up after 30 seconds.
- `follow_redirects=True` — if the server says "this page moved here", follow it.
- `r = c.get(url)` — actually do the HTTP GET request. `r` is the response object.
- `r.raise_for_status()` — if the server returned an error (404, 500, etc.), throw an exception. We want loud failures.
- `return r.text` — give back the page's HTML as a big string.

That's it. We just downloaded a webpage in 6 lines.

### Step 3.2 — Parsing wealthim.ru with regex

`wealthim.ru` puts its NAV history into a regular HTML `<table>`. We need to pull out the (date, NAV) pairs.

The trick: instead of parsing HTML properly (complicated), we strip ALL the tags and then look for date-then-number patterns in the leftover text.

```python
import re

WEALTHIM_PAIR = re.compile(r"(\d{2}\.\d{2}\.\d{4})\s+(\d+[,.]\d{2,4})")

def parse_wealthim(html: str) -> list[tuple[str, float]]:
    # 1. Remove <script>...</script> blocks (they have noisy JS code)
    text = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.S | re.I)
    # 2. Remove every other HTML tag (<div>, <span>, etc.)
    text = re.sub(r"<[^>]+>", " ", text)
    # 3. Collapse whitespace runs into single spaces
    text = re.sub(r"\s+", " ", text)
    # 4. Find all "DD.MM.YYYY <number>" patterns
    pairs = WEALTHIM_PAIR.findall(text)
    rows, seen = [], set()
    for d, v in pairs:
        if d in seen:
            continue
        seen.add(d)
        rows.append((d, float(v.replace(",", "."))))
    rows.sort(key=lambda x: datetime.strptime(x[0], "%d.%m.%Y"))
    return rows
```

**What's a regex?** A pattern language for finding stuff in text.

The pattern `(\d{2}\.\d{2}\.\d{4})\s+(\d+[,.]\d{2,4})` reads as:
- `\d{2}` — exactly 2 digits
- `\.` — a literal dot
- `\d{2}` — 2 more digits
- `\.\d{4}` — dot, 4 digits → that's `DD.MM.YYYY`
- `\s+` — one or more whitespace characters (space, tab, newline)
- `\d+` — one or more digits
- `[,.]` — either `,` or `.` (Russian uses comma as decimal separator)
- `\d{2,4}` — 2 to 4 more digits → that's `123,45` or `12.3456`

Each `( ... )` group "captures" the matched text so we can grab it. So `findall` returns a list of `(date_str, value_str)` tuples.

The dance:
- `re.sub(pattern, replacement, text)` → "find this pattern, replace it" (we replace with space to nuke unwanted stuff)
- `WEALTHIM_PAIR.findall(text)` → "give me all matches"
- `seen` is a set we use to skip duplicate dates (the page sometimes shows the same date twice).
- `float(v.replace(",", "."))` → convert string `"111,45"` to actual number `111.45`.
- `rows.sort(key=lambda x: ...)` → sort by date. `lambda x: ...` is an inline mini-function.

### Step 3.3 — Parsing first-am.ru by finding embedded JSON

`first-am.ru` is built differently. They embed the FULL fund history as a JavaScript variable inside the page:

```html
<script>
  var chartData = [
    {"dateFormat":"30.04.2026","price":2090.38,"net_assets":426387678100, ...},
    {"dateFormat":"29.04.2026","price":2090.11, ...},
    ...
  ];
</script>
```

This is **gold**. We don't have to parse a rendered HTML table — the data is right there as structured JSON. We just need to grab it.

```python
import json

FIRSTAM_CHART = re.compile(r"var\s+chartData\s*=\s*(\[.*?\]);", re.S)

def parse_firstam(html: str) -> list[tuple[str, float]]:
    m = FIRSTAM_CHART.search(html)
    if not m:
        raise ValueError("chartData not found")
    data = json.loads(m.group(1))                    # parse the [...] block as JSON
    rows = [(row["dateFormat"], float(row["price"])) for row in data]
    rows.sort(key=lambda x: datetime.strptime(x[0], "%d.%m.%Y"))
    return rows
```

Tricks here:
- `re.S` flag makes `.` match newlines too (the JSON is multi-line).
- `m.group(1)` gives the captured `[...]` block as a string.
- `json.loads(text)` turns JSON text into Python lists/dicts.
- `[(row["dateFormat"], float(row["price"])) for row in data]` is a **list comprehension** — Python's elegant way to say "for each row, give me a tuple of date and price".

> **Lesson learned:** when scraping, always ask "where does THIS site's data actually live?" Sometimes it's an HTML table, sometimes a JSON blob, sometimes an AJAX endpoint. Look at the page source (Ctrl+U in browser) before reaching for fancy tools.

### Step 3.4 — Computing % deltas

Once we have a list of `[(date, NAV), (date, NAV), ...]` for each fund, we compute "what changed each day".

```python
def compute_deltas(history, n_days):
    # take the last n_days+1 entries (need n+1 points to compute n deltas)
    tail = history[-(n_days + 1):]
    deltas = []
    for i in range(1, len(tail)):
        prev_v = tail[i - 1][1]                     # previous day's NAV
        cur_d, cur_v = tail[i]                      # current day's date & NAV
        pct = (cur_v - prev_v) / prev_v * 100       # percentage change
        deltas.append({"date": cur_d, "nav": cur_v, "delta_pct": pct})
    total_pct = (tail[-1][1] - tail[0][1]) / tail[0][1] * 100
    return {
        "baseline_date": tail[0][0],
        "baseline_nav": tail[0][1],
        "deltas": deltas,
        "total_pct": total_pct,
    }
```

- `history[-(n_days + 1):]` — Python slicing. `history[-5:]` means "last 5 elements". Negative indices count from the end.
- The math: `(new - old) / old * 100` is the standard percentage change formula.
- `total_pct` compares the FIRST baseline to the LAST value — cumulative change over the whole period.
- Returns a Python dict (key→value mapping). Easy to pass around and easy to read in Excel.

### Step 3.5 — Building Excel with openpyxl

Excel files (`.xlsx`) are actually ZIP archives full of XML. You DON'T want to write that by hand. `openpyxl` does it for you.

The basic recipe:

```python
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill, Border, Side

wb = Workbook()                                     # new workbook
ws = wb.active                                      # the default sheet
ws.title = "Сводка"                                 # rename it

# Write a value
c = ws.cell(row=1, column=1, value="Привет, директор")
c.font = Font(bold=True, size=14, color="184EA1")   # blue, bold, 14pt
c.alignment = Alignment(horizontal="center")

# Color the cell background
c.fill = PatternFill("solid", fgColor="E8EEF7")     # light blue

# Set column width and row height
ws.column_dimensions["A"].width = 22
ws.row_dimensions[1].height = 28

# Merge cells (visually fuse multiple into one)
ws.merge_cells("A1:K1")

# Number format (e.g., "+0.05%" with sign)
c.number_format = "+0.0000%;-0.0000%;0.0000%"

# Save the file
wb.save("report.xlsx")
```

Our `build_xlsx` function does this for ~50 cells across 10 fund blocks. It looks long, but it's just the same recipe repeated, with helpers:
- `render_block(ws, fund, start_row, col_offset, styles, theme)` draws ONE fund's mini-table at given coordinates.
- The `theme` dict carries colors so the same function renders blue for the left side (ВИМ) and green for the right side (Первая).

The clever trick: by passing `col_offset=1` we render in columns A-E, and by passing `col_offset=7` we render in columns G-K. Column F stays empty as a visual separator. Same code, two locations — that's why the report has a side-by-side layout without code duplication.

### Step 3.6 — Sending to Telegram

Telegram has a "Bot API" — a simple REST interface. To send a file, you POST to `sendDocument`:

```python
def send_telegram(token, chat_id, file_path, caption):
    url = f"https://api.telegram.org/bot{token}/sendDocument"
    with open(file_path, "rb") as f:
        files = {"document": (file_path.name, f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        data = {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"}
        r = httpx.post(url, files=files, data=data, timeout=60)
    if r.status_code != 200 or not r.json().get("ok"):
        raise RuntimeError(f"telegram send failed: {r.status_code} {r.text}")
    return r.json()
```

- `f"https://api.telegram.org/bot{token}/sendDocument"` — Python f-string. The `{token}` gets replaced with the variable's value.
- `open(file_path, "rb")` — open the xlsx in binary read mode (`b` = binary, since it's not text).
- `files={"document": (filename, file_object, mime_type)}` — httpx's way of doing multipart upload. Telegram expects the file under the form field name `document`.
- `data={"chat_id": ..., "caption": ...}` — extra parameters. `chat_id` says who gets it, `caption` is the message text below the file.
- `parse_mode: "HTML"` — lets you use `<b>`, `<i>` tags in the caption.

To find a person's `chat_id`: the bot has to be /start'd by them first, then we read `getUpdates`. The `get_chat_ids.py` helper does this.

### Step 3.7 — The orchestrator (`main()`)

This ties everything together:

```python
def main():
    args = parse_args()                             # CLI flags
    env = load_env()                                # read .env file for token/chat
    n_days = determine_days(args.days)              # 1 if Mon, 4 if Fri, else 5

    left = collect(WEALTHIM_FUNDS, n_days)          # fetch+parse 5 funds
    right = collect(FIRSTAM_FUNDS, n_days)          # fetch+parse 5 funds

    label = period_label(left, right)               # "с четверга 24.04 по четверг 30.04 (4 торг. дня)"
    out_path = OUT_DIR / f"funds_report_{ts}.xlsx"
    build_xlsx(left, right, label, out_path)        # generate Excel

    for chat_id in chat_ids:
        send_telegram(token, chat_id, out_path, caption)  # ship it
```

That's the whole program in 8 lines. Everything else is implementation detail.

---

## Part 4 — Bonus: the discovery script

Before we picked the top 10 funds, we needed to know which funds even EXIST and which performed best. That's `discover_funds.py`. Two things worth knowing:

**1) Parallel HTTP with ThreadPoolExecutor**

74 funds × 1 second each = 74 seconds if done one at a time. Using 8 parallel workers, it took 33 seconds. The magic:

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

with ThreadPoolExecutor(max_workers=8) as ex:
    futures = [ex.submit(process_fund, f) for f in all_funds]
    for completed_future in as_completed(futures):
        results.append(completed_future.result())
```

`ex.submit(...)` schedules a function to run on a worker thread. `as_completed(...)` yields each future as it finishes. Python handles all the thread bookkeeping.

**2) Wealthim's secret xlsx export endpoint**

The fund pages only show the most recent ~20 days of NAV. But hidden in the page source is a form pointing to:
```
/local/templates/new/components/articul/quotes/.default/xlsx.php
```

Filling that form's hidden parameters (FOND_ID, IBLOCK_ID, from, to dates) and POSTing returns an Excel file with the FULL history. We use `openpyxl.load_workbook(io.BytesIO(response.content))` to read the response straight into memory.

Lesson: **always look at HTML forms in the page source.** They often reveal data endpoints not advertised anywhere.

---

## Part 5 — Files in this project

```
ru-funds-report/
├── funds_report/           ← the package. Each file does one job.
│   ├── config.py           ← reads funds.yaml + .env
│   ├── parsers.py          ← pure parsers (HTML/xlsx → dates + Decimals)
│   ├── scrape.py           ← HTTP fetch + parser dispatch
│   ├── metrics.py          ← Δ%, cumulative, anomaly flags, period label
│   ├── excel.py            ← build the side-by-side xlsx
│   ├── notify.py           ← send to Telegram
│   └── cli.py              ← orchestration + argparse + logging
├── scripts/
│   ├── discover_funds.py   ← enumerate all funds + rank by 1-year return
│   └── get_chat_ids.py     ← print recipient chat_ids after they /start the bot
├── tests/                  ← pytest (no network, no clock — pure tests)
├── data/
│   ├── funds.yaml          ← which funds + sanity thresholds (anomaly flag, staleness)
│   └── discovery.json      ← snapshot of every fund's 1-year return
├── docs/
│   ├── BUILDLOG.md         ← agentic dev journal — how this was built
│   └── Teaching.md         ← this file
├── .env                    ← bot token + recipient chat_ids (gitignored)
├── pyproject.toml          ← Python project metadata + dependencies
└── README.md               ← short overview, quickstart
```

**To run the report manually:**
```powershell
python -m funds_report --days 4
```

`--days N` overrides the auto-detect. Useful for testing.

**To regenerate without sending to Telegram:**
```powershell
python -m funds_report --days 4 --no-send
```

**To run tests:**
```powershell
python -m pytest
```

---

## Part 6 — What you'll learn next if you keep going

In rough order of how I'd suggest tackling them:

1. **Python basics** — variables, lists, dicts, if/else, for loops, functions. Spend an evening on https://docs.python.org/3/tutorial/ or any free YouTube intro.
2. **Virtual environments** — `python -m venv venv` then `pip install` per project, so libraries don't pollute globally.
3. **Type hints** — those `: str` and `-> list` annotations. They make code self-documenting and catch bugs early.
4. **Error handling** — `try / except` to handle "what if the website is down". Currently the script crashes loudly; a more polished version retries and reports the failure.
5. **Logging** — replace `print()` with the `logging` module so you have timestamped log files when the script runs at 9 AM with you asleep.
6. **`requests` vs `httpx`** — both work; httpx is newer. Either is fine.
7. **`pandas`** — game-changer for any tabular data. The whole compute-deltas function could become 3 lines with pandas: `df.pct_change()`, `df.cumsum()`, etc.
8. **`asyncio`** — for true concurrency without threads. Overkill here, but useful for hundreds of API calls.
9. **CLI tools** — replace argparse with `typer` or `click` for nicer CLIs.
10. **Web scraping at scale** — `playwright` for sites that need a real browser; rotating proxies; rate-limiting.

If you want a small starter project to learn on, here's an idea: write a script that polls one of your VPS servers' status page and DM's you on Telegram if anything's down. Same pattern as this report — fetch, parse, decide, send.

---

## Part 7 — Why this design choice and not that one

Some decisions worth understanding:

| Decision | Why |
|---|---|
| Pure Python, no LLM at runtime | LLMs are non-deterministic. We need EXACT numbers. Regex/JSON parsing always returns the same output for the same input. |
| `httpx` not `selenium` | Both target sites serve full HTML on first request. No need for a real browser. Selenium would be 100× slower and need 500MB of Chromium. |
| `openpyxl` not `xlsxwriter` | Both work. `openpyxl` can also READ files (we needed it for wealthim's xlsx export endpoint). One library, both jobs. |
| Telegram, not email | You requested it. Bonus: simpler than SMTP (no auth chains, no spam folder, no attachment size limits at 50MB). |
| `.env` file for secrets | Industry standard. Keeps tokens out of the code, easy to rotate, easy to gitignore. |
| Side-by-side layout in xlsx | Director's eyes don't have to scroll vertically through 10 fund blocks. Two columns of 5 fits on one screen. |
| Hardcoded list of 10 funds | Could be in `funds.yaml`, but for 10 it's overkill. If we ever go to 40+, we move it to YAML. |

---

## Part 8 — When something breaks

Future-you, opening this in 6 months because the script stopped working:

1. **Run it manually** with `python funds_report.py --days 4 --no-send` and read the output.
2. **If it crashes on `parse_wealthim`**: site changed their HTML. Open the URL in browser, inspect the table, update the regex.
3. **If it crashes on `parse_firstam`**: they renamed `chartData` to something else, or removed the inline JSON. Look at page source, find the new variable name, update `FIRSTAM_CHART`.
4. **If Telegram fails**: token expired or bot got blocked. Run `get_chat_ids.py` to verify the bot still works.
5. **If Task Scheduler doesn't fire**: PC was asleep. Set power options "never sleep during business hours" + Task Scheduler "Wake the computer to run this task".

Loud failure (raised exception with stack trace) is GOOD. Silent wrong numbers are BAD. The script is designed for the former.

---

That's it. You now know roughly what every line does. The rest is just typing.
