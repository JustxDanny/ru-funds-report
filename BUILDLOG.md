# Build Log

How this was built, in order. Written for anyone curious about agentic
software development — what gets short-circuited when you build with an
LLM in the loop, and what doesn't.

The whole thing — from "is this even feasible?" to a tested production-shaped
package — happened in a single afternoon session. Total wall time ≈ 4 hours,
of which most was UX iteration and verification. I'm Daniel; the agent is
Claude Opus 4.7 running in Claude Code.

## 0. The ask

A friend wanted to see his Russian PIF funds' стоимость пая as it moved, not
once a month from a paper statement. Twice a week, Telegram, Excel attached,
top-performing funds from each of two managers.

His first instinct was to ask whether `gemini-cli` could do this — he'd heard
LLM-driven scrapers were the new hotness. That framing turned out to be the
single most important thing to push back on.

## 1. Verify before scaffolding

I asked for an honest feasibility check, not a build plan. The agent:

1. Confirmed `gemini-cli` was installed and what tier it was on (read
   `~/.gemini` config, hit Google's `loadCodeAssist` endpoint to verify
   subscription state).
2. Asked it to fetch one fund page and return JSON.
3. Read stderr — every `web_fetch` call had failed with a "Malformed URL"
   bug specific to headless mode. The CLI was silently degrading to
   `google_web_search` snippets. Output looked plausible. It wasn't live
   data.
4. Verified by curling the same page raw and parsing it with regex — values
   matched. Confirmed: the LLM-driven path can return correct numbers,
   but you can't tell when it's lying.

**Decision:** kill `gemini-cli` from the runtime path. Use deterministic
Python. Recorded in `README.md`.

## 2. Smoke test on three funds

Before any structure, the agent built the smallest thing that could fail:
fetch three funds (one per page-listing's first row), parse, print deltas.
Two parsers — wealthim.ru rendered tables (regex) and first-am.ru embedded
`chartData` JSON (json.loads). Each returned ~5 trading days of NAV.

The friend cross-checked four numbers against the live websites. They
matched within rounding. Green light.

## 3. UX iteration loop

Now the only thing that actually mattered: does the spreadsheet read well?

Iterations, in order:

- v1: stacked vertical layout. Felt cramped.
- v2: side-by-side, blue/green theming per manager. Better.
- v3: feedback — "база" row felt redundant, the "ОГО за период" was being
  truncated by column width. Fixed both: baked the baseline into the fund
  header line, widened col A.
- v4: added timestamp subtitle, period label with weekday names ("с
  четверга 24.04 по четверг 30.04"). Russian grammar bug — needed
  genitive after "с", accusative after "по", and proper plural inflection
  for `1/2-4/5+` days. Fixed with two lookup tables and a `plural_days()`
  helper.

Each iteration was one pass. The user looked, said what felt off, the
agent fixed it. No design docs, no reviews — the spreadsheet was the
artifact and the user was the only judge.

## 4. The discovery script

Before locking the production fund list, I ran a separate script
(`scripts/discover_funds.py`) that:

1. Scraped both managers' fund-listing pages.
2. Fetched all 74 fund pages in parallel (8-worker `ThreadPoolExecutor`).
3. Computed each fund's 1-year return.
4. Ranked.

First run: wealthim funds all errored with "no 1y baseline" — their
product pages only render ~20 trading days of history. A separate hunt
through page source revealed a hidden form posting to
`/local/templates/.../xlsx.php` — the site's own xlsx export endpoint.
Filling its hidden parameters (`FOND_ID`, `IBLOCK_ID`, date range) returned
a full-history Excel file. Parsed in-memory with `openpyxl` from
`io.BytesIO`. 1-year returns now compute cleanly.

This endpoint became the production scraper for wealthim — same site,
4-decimal precision (vs 2 on the rendered page). Win.

## 5. Hardening pass

The user said: "make better — accuracy first, speed irrelevant."

Concrete changes:

- **Decimal arithmetic.** Replaced every `float` in financial paths with
  `decimal.Decimal` at 28-digit precision. NAV values come in via
  `Decimal(str(x))` to avoid float→Decimal contamination.
- **Cross-validation.** The cumulative % is computed two ways — direct
  ratio (`latest / baseline - 1`) and compounded daily factors. They
  must match within `0.0001%` or the script raises. Catches drift bugs
  the user would never notice.
- **Anomaly flags.** Daily |Δ| ≥ 3% gets flagged in the xlsx ("⚠ аномалия"
  in the notes column, amber font on the value). The threshold lives
  in `funds.yaml` so it's tunable without touching code.
- **Staleness detection.** If the latest NAV is older than `max_staleness_days`
  (default 7), a warning row appears under the fund block. Catches the
  case where a site's data feed quietly stops.
- **Loud failures.** Bad NAV (≤0), missing `chartData`, missing form,
  history shorter than the window — all raise. Cron job will alert the
  operator; nobody silently sends the director +0.00% for a crashed feed.
- **Real bug found by tests.** The window-too-short check used `len(tail) < 2`
  which trivially passed when the *whole* history was shorter than the
  requested window. Fixed to `len(history) < n_days + 1`. Test commit.

## 6. Refactor for shape

At this point everything was in two files (`funds_report.py`, `discover_funds.py`)
with duplicated parsers. Refactor into a package:

- `config.py` — yaml-backed `Fund` and `Sanity` dataclasses
- `parsers.py` — pure functions (bytes/str → `list[(date, Decimal)]`)
- `scrape.py` — HTTP + parser dispatch
- `metrics.py` — `compute_report`, validation, period-label formatting
- `excel.py` — xlsx rendering
- `notify.py` — Telegram delivery
- `cli.py` — orchestration with proper logging + exit codes

Pure parsers ↔ pure metrics ↔ I/O at the edges. 22 unit tests, none touching
the network or the clock.

## 7. What's not in here

- A web UI. Doesn't need one.
- A database. The Excel is the artifact.
- Async I/O. ~10 funds × 1 second each is fine.
- Retry logic. If the scrape fails, fail loud and re-run.
- A cron service. Windows Task Scheduler does it. The script is invoked,
  not a daemon.
- An LLM at runtime. The numbers must be reproducible.

## Reflections — what agentic engineering changes

Three things actually shifted versus my normal workflow:

1. **The "verify, don't assume" reflex.** When I asked the agent if
   `gemini-cli` would work, it didn't say yes/no. It read the configs,
   hit endpoints, read stderr, cross-checked — *then* answered. The fact
   that it picked apart its own positive-looking output (the JSON looked
   right but came from search snippets) is the move I wouldn't have made
   on autopilot.

2. **Iteration is cheap, so iterate.** UX changes that I'd normally batch
   ("let me sketch the whole layout first") I instead asked for one at a
   time. Each round took ~30 seconds of agent time. That made it easy to
   discover I didn't actually want what I'd specified.

3. **Verification is still mine.** When the agent reported "+0.06%" for a
   fund, I cross-checked four numbers against live sites. The agent does
   not get the last word on whether the output is correct — I do, because
   wrong numbers go to a director.

The system prompt for this session was set to "caveman mode" — every
intermediate response was terse fragments, full sentences only for
artifacts (this file included). Saved a lot of tokens, didn't lose any
substance.
