# Winterclash 2026 Schedule Agent

A self-healing web scraper that polls the [Winterclash 2026 schedule page](https://www.winterclash.com/schedule-2026/) every 15 minutes and keeps `schedule.json` up to date. When the page's HTML structure changes and breaks parsing, the agent calls Google Gemini to automatically rewrite the scraper — no manual intervention needed.

## Features

- Polls every 15 minutes and writes `schedule.json` only when the schedule actually changes
- Detects HTML structural changes via a tag+class fingerprint (ignores normal content updates)
- Self-heals: when parsing breaks, sends the new HTML to Gemini, which rewrites `scraper.py`
- Validates the healed scraper against the live page before saving it
- Graceful shutdown on `Ctrl+C`

## Project structure

```
wc26-schedule-agent/
├── schedule_agent.py   # Main agent — poll loop, fingerprinting, self-healing
├── scraper.py          # HTML parser (auto-replaced by Gemini when it breaks)
├── schedule.json       # Output — updated only when the schedule changes
├── requirements.txt    # Python dependencies
└── .agent_state.json   # Auto-created — stores fingerprint & last-run timestamp
```

## Requirements

- Python 3.10+
- A [Gemini API key](https://aistudio.google.com/apikey) (only needed for self-healing)

## Setup

**1. Install dependencies**

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**2. Set your Gemini API key**

```bash
export GEMINI_API_KEY=AIza...
```

Add it to your shell profile (`~/.zshrc`, `~/.bashrc`) to persist across sessions. The agent runs without this key, but self-healing will be disabled.

**3. Run the agent**

```bash
# Foreground
.venv/bin/python3 schedule_agent.py

# Single tick (useful for testing)
.venv/bin/python3 -c "import schedule_agent; schedule_agent.tick()"
```

The agent runs in the foreground and logs every action with a UTC timestamp. Press `Ctrl+C` to stop.

## Output format

`schedule.json` is updated in place whenever a change is detected:

```json
{
  "lastUpdated": "2026-02-26T15:52:32.768111+00:00",
  "url": "https://www.winterclash.com/schedule-2026/",
  "days": [
    {
      "date": "Thursday / 26th February 2026",
      "events": [
        { "time": "05:00 p.m.", "event": "Doors open" },
        { "time": "05:00 p.m.", "event": "Open Session" },
        { "time": "07:00 p.m.", "event": "Panel: Beyond Tricks..." }
      ]
    }
  ]
}
```

Date and time strings are taken verbatim from the page — no normalisation is applied.

## How self-healing works

```
Every 15 minutes:
  1. Fetch the page HTML
  2. Compute structural fingerprint (tag+class hash, no text content)
  3. Run scraper.py → parse_schedule(html)
         │
         ├─ OK + fingerprint unchanged → compare to schedule.json → save if changed
         │
         └─ Error / empty result / fingerprint changed
               │
               ▼
         Send to Gemini (gemini-3.1-pro-preview):
           - Failure reason
           - Current scraper.py
           - Relevant HTML section
               │
               ▼
         Validate healed code against live HTML
           ├─ Returns data → overwrite scraper.py → continue tick
           └─ Still fails → log warning, skip update
```

The fingerprint hashes only the structural skeleton of the page (tag names and CSS classes), so it changes when the site is redesigned but not when event times or names are updated.

## Running in the background

```bash
nohup .venv/bin/python3 schedule_agent.py > agent.log 2>&1 &
echo $! > agent.pid       # save the PID to stop it later
tail -f agent.log         # watch the log
kill $(cat agent.pid)     # stop the agent
```

## Troubleshooting

**"No schedule data parsed"** — The page structure may have changed significantly. If `GEMINI_API_KEY` is set, the agent will attempt to self-heal automatically on the next tick. Check `agent.log` for details.

**"GEMINI_API_KEY not set — self-healing disabled"** — Set the env var as shown in Setup. The agent will still poll and update `schedule.json` as long as the current `scraper.py` works.

**"Healed scraper returned empty result — discarding"** — The Gemini-generated scraper also failed to parse the page. The page may be temporarily down or its structure has changed drastically. The existing `scraper.py` and `schedule.json` are left untouched.
