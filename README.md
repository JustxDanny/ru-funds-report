# ru-funds-report

Twice-weekly NAV report for Russian mutual funds. Pulls стоимость пая from
[wealthim.ru](https://www.wealthim.ru) and [first-am.ru](https://www.first-am.ru),
computes per-day deltas + cumulative for the chosen window, builds an Excel and
sends it via Telegram.

Built to help a friend track real-time fund movement instead of waiting on
monthly statements.

## Quickstart

```bash
git clone https://github.com/JustxDanny/ru-funds-report
cd ru-funds-report
python -m pip install -e .
cp .env.example .env                          # then fill in the bot token
python -m funds_report --days 4 --no-send     # dry run, prints xlsx path
python -m funds_report                        # live run, sends to Telegram
```

`--days` defaults to 1 on Mondays, 4 on Fridays, 5 otherwise. Pass an explicit
value to override.

## What's in the report

A side-by-side Excel: blue side = wealthim.ru funds, green side = first-am.ru
funds. For each fund: the previous-trading-day baseline, then a row per
trading day in the window with daily Δ% and compounded cumulative Δ%. Anomalies
(|Δ| ≥ 3% or stale data) are flagged inline.

Russian throughout — director-readable. Numbers carry 4 decimals where the
source provides them.

## Architecture

```
funds.yaml ──► config.py
                  │
                  ▼
   scrape.py ──► parsers.py     (HTTP + parse → list[(date, Decimal)])
                  │
                  ▼
              metrics.py        (Δ%, cumulative, anomaly flags, cross-validation)
                  │
                  ▼
              excel.py          (themed xlsx, two-column layout)
                  │
                  ▼
              notify.py         (Telegram sendDocument, multi-recipient)
                  │
                  ▼
                cli.py          (orchestration, logging, exit codes)
```

Pure-function parsers that take bytes/string and return decimals — easy to
unit-test, no clock or network in the test path.

## Decisions worth knowing

**Wealthim authoritative source.** The product page renders 2-decimal NAV
values; the same site exposes a hidden `xlsx.php` export endpoint with
4-decimal data. We use the export — same site, more precision, simpler regex.
Discovered by reading the page's hidden `<form id="export_xlsx">`.

**First-am embedded JSON.** Their pages embed full NAV history as
`var chartData = […]` inside `<script>`. We parse the literal directly rather
than the rendered HTML table — closer to the data layer, drift-resistant.

**Decimal, not float.** All NAV math goes through `decimal.Decimal`. A 0.0001%
cross-validation tolerance catches inconsistencies between two independent
total computations (direct ratio vs compounded daily factors).

**No LLM at runtime.** An earlier prototype used `gemini-cli` to scrape the
pages with `web_fetch`. It was non-deterministic — sometimes the tool
silently degraded to Google search snippets. For numbers going to a director,
non-deterministic is unacceptable. Replaced with regex/JSON parsing.

**Loud failure over silent wrong numbers.** Bad NAV (≤0), parser miss, stale
data — all raise. The cron will alert on a missed run; nobody emails the
director "+0.00%" for a fund that actually crashed.

## Operate

```bash
# Re-rank all 70+ funds by 1-year return (output → discovery.json):
python scripts/discover_funds.py

# After someone /starts the bot, capture their chat_id:
python scripts/get_chat_ids.py

# Run the report manually any day:
python -m funds_report --days 4
```

Schedule via Windows Task Scheduler (Mon + Fri 09:00 local). PC must be
configured with "wake to run task" if it sleeps.

## Tests

```bash
python -m pytest         # 22 tests, ~0.2s, no network
```

## Files

```
ru-funds-report/
├── funds.yaml             10 production funds + sanity thresholds
├── funds_report/          the package (config, parsers, scrape, metrics, excel, notify, cli)
├── scripts/               operational helpers (discover, get_chat_ids)
├── tests/                 pytest suite + tiny html fixture
├── discovery.json         current 74-fund inventory with 1y returns
├── Teaching.md            walkthrough for someone learning Python from this repo
├── BUILDLOG.md            how it was built — agentic dev journal
└── pyproject.toml
```

## License

MIT.
