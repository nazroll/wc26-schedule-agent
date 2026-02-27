"""
scraper.py

This module provides a robust web scraper to parse the Winterclash schedule.
It exposes exactly one public function `parse_schedule(html: str) -> list`
which returns a list of dictionaries, each representing a day's schedule.
Any failure during parsing gracefully results in an empty list.
"""

import re
from bs4 import BeautifulSoup

def parse_schedule(html: str) -> list:
    try:
        if not html:
            return []
        
        soup = BeautifulSoup(html, 'html.parser')
        
        # Extract all text, separating distinct elements with newlines
        text = soup.get_text(separator='\n', strip=True)
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        
        # Regex for dates: e.g. "Friday / 27th February 2026" or "Saturday - 28th February 2026"
        date_re_1 = re.compile(r'(?i)^([a-z]+)[\s/,|\-]+(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]+)[\s,]+(\d{4})$')
        # Regex for dates: e.g. "Thursday, February 26, 2026"
        date_re_2 = re.compile(r'(?i)^([a-z]+)[\s,]+([a-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?[\s,]+(\d{4})$')
        
        # Regex for times
        # Matches formats like "15:00", "03:00 PM", "3 PM", "15.00"
        T = r'(?:\d{1,2}[:.hH]\d{2}(?:\s*[aA][mM]|\s*[pP][mM])?|\d{1,2}\s*(?:[aA][mM]|[pP][mM]))'
        # Negative lookahead part to prevent time ranges bleeding into event descriptions
        T_lookahead = r'(?:\d{1,2}[:.hH]\d{2}|\d{1,2}\s*(?:[aA][mM]|[pP][mM]))'
        
        # Matches a single time or a range like "14:00 - 15:00"
        R = fr'{T}(?:\s*(?:[-–]|to)\s*{T})?'
        
        time_exact_re = re.compile(fr'^{R}$')
        time_mixed_re = re.compile(fr'^({R})[\s\-–:]+(?!{T_lookahead})(.+)$')
        
        days = []
        current_date_str = None
        current_events = []
        
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # 1. Check if line is a Date
            m1 = date_re_1.match(line)
            m2 = date_re_2.match(line)
            
            if m1 or m2:
                if current_date_str and current_events:
                    days.append({"date": current_date_str, "events": current_events})
                
                if m1:
                    day_name = m1.group(1).capitalize()
                    day_num = m1.group(2)
                    month = m1.group(3).capitalize()
                    year = m1.group(4)
                else:
                    day_name = m2.group(1).capitalize()
                    month = m2.group(2).capitalize()
                    day_num = m2.group(3)
                    year = m2.group(4)
                    
                current_date_str = f"{day_name}, {month} {day_num}, {year}"
                current_events = []
                i += 1
                continue
            
            # If we haven't found a date yet, ignore other content
            if not current_date_str:
                i += 1
                continue
            
            # 2. Check if line is a mixed Time + Event (e.g. "15:00 - Doors open")
            m_mixed = time_mixed_re.match(line)
            if m_mixed:
                time_str = m_mixed.group(1).strip()
                event_str = m_mixed.group(2).strip()
                event_str = re.sub(r'^[-–:]\s*', '', event_str)
                current_events.append({"time": time_str, "event": event_str})
                i += 1
                continue
            
            # 3. Check if line is an exact Time (event is on the next line)
            m_exact = time_exact_re.match(line)
            if m_exact:
                time_str = line.strip()
                event_str = "Unknown event"
                
                if i + 1 < len(lines):
                    next_line = lines[i+1]
                    # Verify the next line isn't another date or time
                    if not (date_re_1.match(next_line) or 
                            date_re_2.match(next_line) or 
                            time_exact_re.match(next_line) or 
                            time_mixed_re.match(next_line)):
                        event_str = next_line.strip()
                        i += 1  # consume the event line
                
                event_str = re.sub(r'^[-–:]\s*', '', event_str)
                current_events.append({"time": time_str, "event": event_str})
                i += 1
                continue
            
            i += 1
            
        # Append the last day if it has events
        if current_date_str and current_events:
            days.append({"date": current_date_str, "events": current_events})
            
        return days

    except Exception:
        return []