# Winterclash 2026 Schedule Agent

A Python agent that polls the [Winterclash 2026 schedule page](https://www.winterclash.com/schedule-2026/) every 15 minutes and keeps `schedule.json` up to date. If the page's HTML structure changes in a way that breaks parsing, the agent calls Claude to automatically rewrite the scraper — no manual intervention needed.

## Features

- Polls every 15 minutes and writes `schedule.json` only when the schedule actually changes
- Detects HTML structural changes via a tag+class fingerprint (ignores normal content updates)
- Self-heals: when parsing breaks, sends the new HTML to Claude, which rewrites `scraper.py`
- Validates the healed scraper against the live page before saving it
- Graceful shutdown on `Ctrl+C`

## Project structure

```
wc26-by-claude/
├── schedule_agent.py   # Main agent — poll loop, fingerprinting, self-healing
├── scraper.py          # HTML parser (auto-replaced by Claude when it breaks)
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
pip install -r requirements.txt
```

Or with a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**2. Set your Gemini API key**

```bash
export GEMINI_API_KEY=AIza...
```

Add it to your shell profile (`~/.zshrc`, `~/.bashrc`) to persist it across sessions. The agent runs without this key, but self-healing will be disabled.

**3. Run the agent**

```bash
# If using the venv created above:
.venv/bin/python3 schedule_agent.py

# Or with the venv activated:
python schedule_agent.py
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
        { "time": "07:00 p.m.", "event": "Panel: Beyond Tricks: How Skate Lessons Build Strong Minds and Strong Communities." }
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

**Using nohup (simplest):**

```bash
nohup .venv/bin/python3 schedule_agent.py > agent.log 2>&1 &
echo $! > agent.pid       # save the PID to stop it later
tail -f agent.log         # watch the log
kill $(cat agent.pid)     # stop the agent
```

**Using a macOS LaunchAgent (runs on login, restarts on crash):**

Create `~/Library/LaunchAgents/com.wc26.schedule-agent.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.wc26.schedule-agent</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/nazroll/Projects/wc26-by-claude/.venv/bin/python3</string>
    <string>/Users/nazroll/Projects/wc26-by-claude/schedule_agent.py</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>ANTHROPIC_API_KEY</key>
    <string>sk-ant-...</string>
  </dict>
  <key>StandardOutPath</key>
  <string>/Users/nazroll/Projects/wc26-by-claude/agent.log</string>
  <key>StandardErrorPath</key>
  <string>/Users/nazroll/Projects/wc26-by-claude/agent.log</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
</dict>
</plist>
```

Then load it:

```bash
launchctl load ~/Library/LaunchAgents/com.wc26.schedule-agent.plist
```

To stop:

```bash
launchctl unload ~/Library/LaunchAgents/com.wc26.schedule-agent.plist
```

## Troubleshooting

**"No schedule data parsed"** — The page structure may have changed significantly. If `ANTHROPIC_API_KEY` is set, the agent will attempt to self-heal automatically on the next tick. Check `agent.log` for details.

**"ANTHROPIC_API_KEY not set — self-healing disabled"** — Set the env var as shown in Setup. The agent will still poll and update `schedule.json` as long as the current `scraper.py` works.

**"Healed scraper returned empty result — discarding"** — The Claude-generated scraper also failed to parse the page. The page may be temporarily down or its structure has changed drastically. The existing `scraper.py` and `schedule.json` are left untouched.

**The agent stops unexpectedly** — Use the LaunchAgent setup above to keep it running automatically.
