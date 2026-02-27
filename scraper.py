"""
scraper.py

Parses the Winterclash schedule page by targeting GDLR widget classes.
Exposes exactly one public function `parse_schedule(html: str) -> list`
which returns a list of day dicts. Returns [] on any failure.
"""

import re
from bs4 import BeautifulSoup


def parse_schedule(html: str) -> list:
    try:
        if not html:
            return []

        soup = BeautifulSoup(html, "html.parser")

        # Day headings live in h3.gdlr-core-title-item-title tags
        date_re = re.compile(
            r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)", re.I
        )
        day_headings = [
            h3
            for h3 in soup.select("h3.gdlr-core-title-item-title")
            if date_re.search(h3.get_text())
        ]

        # Each day heading is followed by a .gdlr-core-timeline-item block
        timeline_blocks = soup.select(".gdlr-core-timeline-item")

        days = []
        for idx, heading in enumerate(day_headings):
            date_str = heading.get_text(strip=True)

            if idx >= len(timeline_blocks):
                break
            block = timeline_blocks[idx]

            events = []
            for row in block.select(".gdlr-core-timeline-item-list"):
                # Extract time: decompose bullet sub-divs first so they
                # don't pollute get_text()
                date_div = row.select_one(".gdlr-core-timeline-item-date")
                if not date_div:
                    continue
                for bullet in date_div.select(".gdlr-core-timeline-item-bullet"):
                    bullet.decompose()
                time_str = date_div.get_text(strip=True)

                # Extract event name
                title_div = row.select_one(".gdlr-core-timeline-item-title")
                event_str = title_div.get_text(strip=True) if title_div else ""

                if time_str and event_str:
                    events.append({"time": time_str, "event": event_str})

            if events:
                days.append({"date": date_str, "events": events})

        return days

    except Exception:
        return []
