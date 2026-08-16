# ru-funds-report

**A Telegram bot that keeps an investor close to his funds.**

*[Читать на русском →](README.ru.md)*

---

## The problem

A friend of mine invests in Russian mutual funds (ПИФы). His fund managers send
him a statement **once a month**. By the time it lands, the numbers are history:
he's reacting to something that already happened.

He didn't want a trading terminal. He wanted the answer to one question, twice a
week, in the app he already has open:

> *"How are my funds doing since I last looked?"*

## The solution

Every Monday and Friday morning, a scheduled job wakes up, reads the current
share price (стоимость пая) for the ten funds he actually owns, works out what
changed, builds a clean Excel file, and drops it into his Telegram.

No app to install. No login. No dashboard to remember to check. It just arrives.

```
  Mon / Fri 09:00
        │
        ▼
  scrape 2 fund sites  ──►  compute Δ% per day + cumulative
        │                            │
        │                            ▼
        │                   flag anything weird
        ▼                            │
   build .xlsx  ◄────────────────────┘
        │
        ▼
   📲 Telegram
```

## What he actually receives

A side-by-side Excel sheet, in Russian, readable in ten seconds:

- **Blue side**: funds from wealthim.ru. **Green side**: funds from first-am.ru.
- One row per trading day: the daily change, and the compounded change across the window.
- Anything unusual (a move over 3%, or data that hasn't updated) is **flagged right in the sheet** so it can't be missed.

## About this project

This is a **vibecoded** project. I built it conversationally with
[Claude Code](https://claude.com/claude-code), describing what I wanted, reading
what came back, pushing on the parts that were wrong, and keeping what held up.
The full build diary is in [BUILDLOG.md](docs/BUILDLOG.md), warts included.

I'm early in my journey as a developer, and I learn by shipping things real
people use. This one runs twice a week on a real machine for a real person, and
has done since May 2026.

If you want to learn Python from this codebase, [Teaching.md](docs/Teaching.md)
is a guided walkthrough I wrote for exactly that.

---

## Try it

```bash
git clone https://github.com/JustxDanny/ru-funds-report
cd ru-funds-report
python -m pip install -e .

cp .env.example .env                        # add your Telegram bot token
python -m funds_report --days 4 --no-send   # dry run: just prints the xlsx path
python -m funds_report                      # live run: sends to Telegram
```

`--days` picks itself based on the weekday (1 on Monday, 4 on Friday, 5 otherwise).
Pass a number to override.

**You need:** Python 3.11+, and a Telegram bot token from
[@BotFather](https://t.me/BotFather).

## Run it on a schedule (Windows)

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install_task.ps1
```

Registers a Task Scheduler job for Mon + Fri at 09:00. `WakeToRun` is on, so a
sleeping PC wakes up for it. Logs go to `logs/`. Remove it with
`schtasks /delete /tn funds-report /f`.

---

## How it's built

```
funds.yaml ──► config.py       which funds, and what counts as "weird"
                  │
                  ▼
   scrape.py ──► parsers.py    fetch the pages → list of (date, price)
                  │
                  ▼
              metrics.py       daily Δ%, cumulative Δ%, anomaly flags
                  │
                  ▼
              excel.py         the themed two-column spreadsheet
                  │
                  ▼
              notify.py        Telegram sendDocument, multiple recipients
                  │
                  ▼
                cli.py         orchestration, logging, exit codes
```

The parsers are pure functions: bytes in, decimals out. No clock, no network in
the test path, so the whole suite runs offline in about a fifth of a second.

```bash
python -m pytest      # 22 tests, ~0.2s, no network
```

## Four decisions I'd defend

**Decimal, never float.** Every NAV calculation goes through `decimal.Decimal`.
Two independent methods compute the same total (direct ratio vs. compounded
daily factors) and must agree to within 0.0001%, otherwise the run fails. These
numbers go to someone who makes money decisions with them; "close enough" isn't.

**No LLM at runtime.** The first prototype used an AI CLI to fetch and read the
pages. It was non-deterministic: sometimes it quietly fell back to search
snippets instead of the real data. Fine for a demo, unacceptable for a number
someone acts on. Replaced with plain regex and JSON parsing. *The AI helped me
build it; it doesn't get to be part of it.*

**Fail loudly, never quietly wrong.** A bad price, a parser that stopped
matching, stale data: all raise and abort the run. A missed report gets noticed.
A report that confidently says "+0.00%" about a fund that actually dropped does
real damage.

**Take the data from the cleanest layer available.** wealthim.ru renders prices
at 2 decimals on the page, but exposes a hidden `xlsx.php` export with 4
decimals, found by reading the page's own hidden form. first-am.ru embeds its
full history as a JSON literal inside a `<script>` tag, so we parse that instead
of the rendered table. Both are closer to the source and less likely to break
when someone redesigns the page.

---

## Repo layout

```
ru-funds-report/
├── funds_report/      the package: config, parsers, scrape, metrics, excel, notify, cli
├── scripts/           helpers: discover funds, capture chat IDs, install the task
├── tests/             pytest suite + a small html fixture
├── taskscheduler/     Windows Task Scheduler template
├── docs/              BUILDLOG.md (how it was built) · Teaching.md (learn Python from it)
├── data/              funds.yaml (the 10 tracked funds) · discovery.json (74-fund inventory)
└── pyproject.toml
```

## License

[MIT](LICENSE). Do what you like with it.
