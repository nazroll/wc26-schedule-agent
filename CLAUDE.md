# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Self-healing web scraper that polls the [Winterclash 2026 schedule](https://www.winterclash.com/schedule-2026/) every 15 minutes and writes `schedule.json`. When parsing breaks (HTML structure change or scraper error), the agent calls Google Gemini to automatically rewrite `scraper.py`.

## Commands

```bash
# Setup
python -m venv .venv && .venv/bin/pip install -r requirements.txt

# Run (foreground)
.venv/bin/python3 schedule_agent.py

# Run (background)
nohup .venv/bin/python3 schedule_agent.py > agent.log 2>&1 &

# Run a single tick for testing
.venv/bin/python3 -c "import schedule_agent; schedule_agent.tick()"
```

Self-healing requires `GEMINI_API_KEY` in the environment.

## Architecture

Two-file design with a strict contract between them:

- **schedule_agent.py** — Orchestrator: poll loop, fingerprinting, self-healing via Gemini (`gemini-3.1-pro-preview`), schedule diffing. Dynamically reloads `scraper.py` via `importlib` on every tick.
- **scraper.py** — Pure parser, single public function: `parse_schedule(html: str) -> list[dict]`. This file is auto-generated/overwritten by the agent during self-healing. Must never raise; returns `[]` on failure.

### Self-healing flow

1. Fetch HTML → compute structural fingerprint (SHA256 of tag+class skeleton, ignores text)
2. Run `scraper.parse_schedule(html)`
3. If error, empty result, or fingerprint changed → send HTML + current scraper code + failure reason to Gemini
4. `exec()` the generated code against live HTML to validate before overwriting `scraper.py`

### Data files

- **schedule.json** — Output. Shape: `{ lastUpdated, url, days: [{ date, events: [{ time, event }] }] }`
- **.agent_state.json** — Persists `fingerprint` (HTML structure hash) and `last_run` timestamp between ticks

## Key conventions

- The Winterclash page uses a GDLR timeline widget (`gdlr-core-timeline-item-*` classes), not standard HTML tables. The scraper must target these classes.
- Times come from `.gdlr-core-timeline-item-date`, event names from `.gdlr-core-timeline-item-title`. The bullet sub-divs inside the date element must be decomposed before extracting text.
- Date/time strings are stored verbatim from the page (e.g. `"05:00 p.m."`, `"Thursday / 26th February 2026"`).
- `scraper.py` can be completely rewritten at runtime — do not store agent logic or imports there that aren't part of the parsing contract.
