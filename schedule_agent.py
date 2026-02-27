#!/usr/bin/env python3
"""
Winterclash 2026 Schedule Agent

- Polls https://www.winterclash.com/schedule-2026/ every 15 minutes
- Writes parsed data to schedule.json when the schedule changes
- Computes a structural fingerprint of the page on every fetch
- When the fingerprint changes OR parsing returns empty/errors, the agent
  calls Claude to inspect the new HTML and rewrite scraper.py automatically
- After rewriting, it validates the new scraper before saving it

Requirements:
    pip install requests beautifulsoup4 anthropic

Set ANTHROPIC_API_KEY in your environment for the self-healing feature.
"""

import hashlib
import importlib.util
import json
import os
import re
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ── Paths & constants ─────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent
SCHEDULE_FILE = BASE_DIR / "schedule.json"
SCRAPER_FILE = BASE_DIR / "scraper.py"
STATE_FILE = BASE_DIR / ".agent_state.json"

TARGET_URL = "https://www.winterclash.com/schedule-2026/"
POLL_INTERVAL = 15 * 60  # seconds
REQUEST_TIMEOUT = 30  # seconds

FETCH_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; WinterclashScheduleAgent/1.0)",
    "Accept": "text/html,application/xhtml+xml",
}

# ── Utilities ─────────────────────────────────────────────────────────────────


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(msg: str):
    print(f"[{utcnow()}] {msg}", flush=True)


# ── State persistence ─────────────────────────────────────────────────────────


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2))


# ── HTML structure fingerprinting ─────────────────────────────────────────────


def structural_fingerprint(html: str) -> str:
    """
    Hash the tag+class skeleton of the page, ignoring text content.
    This lets us distinguish a real layout change from a normal content update.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    parts = []
    for tag in soup.find_all(True):
        classes = " ".join(sorted(tag.get("class", [])))
        parts.append(f"{tag.name}[{classes}]")

    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


# ── Dynamic scraper loader ────────────────────────────────────────────────────


def load_scraper():
    """Import scraper.py from disk (always re-reads the file)."""
    spec = importlib.util.spec_from_file_location("scraper", SCRAPER_FILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ── Self-healing via Claude ───────────────────────────────────────────────────


def _extract_schedule_html(html: str, max_chars: int = 15_000) -> str:
    """
    Return the most schedule-relevant section of the HTML to keep
    the Claude prompt compact.
    """
    soup = BeautifulSoup(html, "html.parser")
    weekday_re = re.compile(
        r"Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday", re.I
    )

    # Prefer the smallest container that still holds all day headings
    best = None
    for container in soup.find_all(["main", "article", "section", "div"]):
        if container.find(string=weekday_re):
            snippet = str(container)
            if best is None or len(snippet) < len(best):
                best = snippet

    fallback = str(soup.find("body") or soup)
    result = best if best else fallback
    return result[:max_chars] + ("\n<!-- truncated -->" if len(result) > max_chars else "")


def heal_scraper(html: str, current_code: str, reason: str) -> str | None:
    """
    Ask Gemini to rewrite scraper.py given the current HTML and the failure reason.
    Returns the new source code, or None if unavailable/failed.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        log("GEMINI_API_KEY not set — self-healing disabled.")
        return None

    try:
        from google import genai
    except ImportError:
        log("google-genai package not installed — run: pip install google-genai")
        return None

    schedule_html = _extract_schedule_html(html)

    prompt = f"""You are an expert Python web-scraping engineer.

The Winterclash schedule page ({TARGET_URL}) has either changed its HTML
structure or the current parser is broken. Your task is to write a new,
working scraper.py.

## Failure reason
{reason}

## Current scraper.py
```python
{current_code}
```

## Relevant HTML from the live page
```html
{schedule_html}
```

## Requirements for the new scraper.py
1. Contains exactly one public function with this signature:
       def parse_schedule(html: str) -> list:
2. Returns a list of day dicts:
       [{{"date": "Thursday, February 26, 2026",
         "events": [{{"time": "5:00 PM", "event": "Doors open"}}]}}]
3. Uses BeautifulSoup (bs4) — already installed.
4. Never raises an exception; returns [] on any failure.
5. Handles minor whitespace and text variations robustly.
6. Includes a short module docstring explaining the contract.

Reply with ONLY the raw Python source — no markdown fences, no explanation."""

    client = genai.Client(api_key=api_key)
    try:
        response = client.models.generate_content(
            model="gemini-3.1-pro-preview",
            contents=prompt,
        )
        code = response.text.strip()
        # Strip accidental markdown fences
        code = re.sub(r"^```python\s*\n?", "", code)
        code = re.sub(r"\n?```\s*$", "", code)
        return code
    except Exception as exc:
        log(f"Gemini API error: {exc}")
        return None


def validate_and_save_scraper(new_code: str, html: str) -> bool:
    """
    Validate the new scraper by exec-ing it and running parse_schedule.
    Only writes scraper.py if it successfully returns a non-empty list.
    """
    tmp_globals: dict = {}
    try:
        exec(compile(new_code, "<healed_scraper>", "exec"), tmp_globals)
        parse_fn = tmp_globals.get("parse_schedule")
        if not callable(parse_fn):
            log("Healed code has no parse_schedule() function.")
            return False
        result = parse_fn(html)
        if not result:
            log("Healed scraper returned empty result — discarding.")
            return False
    except Exception as exc:
        log(f"Healed scraper failed validation: {exc}")
        return False

    SCRAPER_FILE.write_text(new_code)
    log(f"scraper.py rewritten successfully ({len(result)} day(s) parsed).")
    return True


# ── Schedule I/O ──────────────────────────────────────────────────────────────


def load_schedule() -> dict | None:
    try:
        return json.loads(SCHEDULE_FILE.read_text())
    except Exception:
        return None


def save_schedule(days: list):
    data = {
        "lastUpdated": datetime.now(timezone.utc).isoformat(),
        "url": TARGET_URL,
        "days": days,
    }
    SCHEDULE_FILE.write_text(json.dumps(data, indent=2))
    return data


def schedules_equal(a: list, b: list) -> bool:
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


# ── Network ───────────────────────────────────────────────────────────────────


def fetch_html() -> str | None:
    try:
        resp = requests.get(TARGET_URL, headers=FETCH_HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.text
    except Exception as exc:
        log(f"Fetch failed: {exc}")
        return None


# ── Agent tick ────────────────────────────────────────────────────────────────


def tick():
    log(f"Fetching {TARGET_URL} …")
    html = fetch_html()
    if html is None:
        return

    state = load_state()

    # ── Structural change detection ───────────────────────────────────────
    new_fingerprint = structural_fingerprint(html)
    old_fingerprint = state.get("fingerprint")
    structure_changed = bool(old_fingerprint and old_fingerprint != new_fingerprint)

    if structure_changed:
        log("HTML structure change detected — may need to self-heal.")

    # ── Ensure scraper.py exists ──────────────────────────────────────────
    if not SCRAPER_FILE.exists():
        log("scraper.py missing — triggering self-heal.")
        _self_heal(html, "", "scraper.py does not exist")
        if not SCRAPER_FILE.exists():
            log("Could not create scraper.py — skipping tick.")
            return

    # ── Try current scraper ───────────────────────────────────────────────
    days = []
    scraper_error = ""
    try:
        scraper = load_scraper()
        days = scraper.parse_schedule(html)
    except Exception:
        scraper_error = traceback.format_exc()
        log(f"Scraper raised an exception:\n{scraper_error}")

    # ── Self-heal if needed ───────────────────────────────────────────────
    needs_heal = structure_changed or scraper_error or not days
    if needs_heal:
        reason = (
            scraper_error
            or ("parse_schedule returned empty list" if not days else "")
            or "HTML structure changed"
        )
        log(f"Self-healing triggered. Reason: {reason[:200]}")
        current_code = SCRAPER_FILE.read_text() if SCRAPER_FILE.exists() else ""
        healed = _self_heal(html, current_code, reason)
        if healed:
            try:
                scraper = load_scraper()
                days = scraper.parse_schedule(html)
                log(f"Healed scraper returned {len(days)} day(s).")
            except Exception as exc:
                log(f"Healed scraper still failing: {exc}")
                days = []

    # ── Guard: nothing to save ────────────────────────────────────────────
    if not days:
        log("No schedule data parsed — skipping schedule.json update.")
        state["fingerprint"] = new_fingerprint
        state["last_run"] = utcnow()
        save_state(state)
        return

    # ── Compare & persist ─────────────────────────────────────────────────
    existing = load_schedule()
    existing_days = (existing or {}).get("days")

    if existing_days and schedules_equal(existing_days, days):
        log("No changes detected.")
    else:
        save_schedule(days)
        total = sum(len(d["events"]) for d in days)
        log(f"schedule.json updated — {len(days)} day(s), {total} total event(s).")

    state["fingerprint"] = new_fingerprint
    state["last_run"] = utcnow()
    save_state(state)


def _self_heal(html: str, current_code: str, reason: str) -> bool:
    new_code = heal_scraper(html, current_code, reason)
    if not new_code:
        return False
    return validate_and_save_scraper(new_code, html)


# ── Entry point ───────────────────────────────────────────────────────────────


def main():
    log("Winterclash 2026 Schedule Agent started.")
    log(f"Polling every {POLL_INTERVAL // 60} minutes. Press Ctrl+C to stop.\n")

    while True:
        try:
            tick()
        except KeyboardInterrupt:
            print("\nAgent stopped.")
            sys.exit(0)
        except Exception:
            log(f"Unexpected error:\n{traceback.format_exc()}")

        log(f"Next check in {POLL_INTERVAL // 60} minutes.\n")
        try:
            time.sleep(POLL_INTERVAL)
        except KeyboardInterrupt:
            print("\nAgent stopped.")
            sys.exit(0)


if __name__ == "__main__":
    main()
