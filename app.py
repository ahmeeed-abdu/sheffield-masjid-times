"""Sheffield masjid prayer-time portal: small, fail-closed proof of concept.

Only the listed, fixed mosque websites are fetched; there is no arbitrary-URL proxy.
Published times must be verified with their mosque before public reliance.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Callable
from zoneinfo import ZoneInfo
import copy
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import unicodedata
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).parent
TZ = ZoneInfo("Europe/London")
PRAYERS = ("fajr", "dhuhr", "asr", "maghrib", "isha")
CACHE_SECONDS = 20 * 60
LOG = logging.getLogger("portal")

# URLs are fixed; not taken from API query parameters (avoids server-side request forgery).
MOSQUES = [{'id': 'huda',
  'name_ar': 'مسجد الهدى',
  'name_en': 'Al-Huda Islamic Centre',
  'area': 'Broomhall',
  'address': 'Hanover St, Sheffield S3 7WT',
  'website': 'https://masjidhudasheff.com/',
  'timetable_url': 'https://masjidhudasheff.com/',
  'source_type': 'html',
  'parser': 'huda'},
 {'id': 'grand',
  'name_ar': 'مسجد شيفلد الكبير',
  'name_en': 'Sheffield Grand Mosque',
  'area': 'Grimesthorpe',
  'address': 'Grimesthorpe Rd, Sheffield S4 8DE',
  'website': 'https://emaantrust.mosqueprayertimes.org/prayer-times',
  'timetable_url': 'https://masjidbox.com/prayer-times/sheffield-grand-mosque-1696948767583',
  'source_type': 'masjidbox_public_page',
  'parser': 'grand_masjidbox'},
 {'id': 'madina',
  'name_ar': 'مسجد المدينة',
  'name_en': 'Madina Masjid Sheffield',
  'area': 'Lowfield',
  'address': '24 Wolseley Rd, Sheffield S8 0ZU',
  'website': 'https://www.madinamasjid.org.uk/',
  'timetable_url': 'https://mawaqit.net/en/madina-masjid-sheffield-sheffield-s8-0zu-united-kingdom',
  'source_type': 'mawaqit_link_only',
  'parser': None},
 {'id': 'risalah',
  'name_ar': 'مسجد الرسالة',
  'name_en': 'Al-Resala (Masjid Risalah)',
  'area': 'Netherthorpe',
  'address': '51 Montgomery Terrace Rd, Sheffield S6 3BW',
  'website': 'https://mosqueprayertimes.org/prayer-times',
  'timetable_url': 'https://mosqueprayertimes.org/prayer-times',
  'source_type': 'html',
  'parser': 'mosque_times'},
 {'id': 'mwh',
  'name_ar': 'مسجد بيت الرعاية الإسلامية',
  'name_en': 'Muslim Welfare House',
  'area': 'Broomhall',
  'address': '10-12 Severn Rd, Sheffield S10 2SU',
  'website': 'https://www.mwhs.org.uk/',
  'timetable_url': 'https://www.mwhs.org.uk/',
  'source_type': 'html',
  'parser': 'mwh_home'},
 {'id': 'rahman',
  'name_ar': 'مسجد الرحمن',
  'name_en': 'Al-Rahman Mosque and Cultural Centre',
  'area': 'Burngreave',
  'address': '9 Gower St, Sheffield S4 7HA',
  'website': 'https://alrahman.mosqueprayertimes.org/prayer-times',
  'timetable_url': 'https://alrahman.mosqueprayertimes.org/prayer-times',
  'source_type': 'html',
  'parser': 'mosque_times'},
 {'id': 'sunnah',
  'name_ar': 'مسجد السنة',
  'name_en': 'Masjid Sunnah Sheffield',
  'area': 'Pitsmoor',
  'address': '18 Kirk St, Sheffield S4 7JX',
  'website': 'https://masjidsunnahsheffield.co.uk/',
  'timetable_url': 'https://masjidsunnahsheffield.co.uk/',
  'source_type': 'html',
  'parser': 'sunnah'},
 {'id': 'baitul',
  'name_ar': 'مسجد بيت المكرم',
  'name_en': 'Baitul Mukarram Jame Masjid',
  'area': 'Highfield',
  'address': '358 London Rd, Sheffield S2 4NB',
  'website': 'https://www.baitulmukarramjamemasjid.com/',
  'timetable_url': 'https://www.baitulmukarramjamemasjid.com/',
  'source_type': 'html_dated_required',
  'parser': 'baitul_dated'},
 {'id': 'makki',
  'name_ar': 'مسجد مكي',
  'name_en': 'Makki Mosque Sheffield',
  'area': 'Heeley',
  'address': 'Plantation Rd, Sheffield S8 9TH',
  'website': 'https://www.makkimosquesheffield.com/',
  'timetable_url': 'https://masjidbox.com/prayer-times/makki',
  'source_type': 'masjidbox_public_page',
  'parser': 'makki_masjidbox'},
 {'id': 'quba',
  'name_ar': 'مسجد قباء ومركز التعليم',
  'name_en': 'Masjid Quba Education Centre (MQEC)',
  'area': 'Attercliffe',
  'address': '120 Worksop Rd, Sheffield S9 3TN',
  'website': 'https://www.yorkshire.com/sheffield/community/mosques/masjid-quba-education-centre-mqec',
  'timetable_url': 'https://www.yorkshire.com/sheffield/community/mosques/masjid-quba-education-centre-mqec',
  'source_type': 'directory_listing',
  'parser': None},
 {'id': 'umar',
  'name_ar': 'مسجد عمر',
  'name_en': 'Masjid Umar (YMA Sheffield)',
  'area': 'Burngreave',
  'address': '306 Barnsley Rd, Sheffield S4 7AH',
  'website': 'https://www.ymasheffield.org/',
  'timetable_url': 'https://www.ymasheffield.org/prayer-timetable',
  'source_type': 'official_pdf_link',
  'parser': None},
 {'id': 'andalus',
  'name_ar': 'مركز الأندلس المجتمعي',
  'name_en': 'Andalus Community Centre',
  'area': 'Sheffield City Centre',
  'address': '43 Townhead St, Sheffield S1 2EB',
  'website': 'https://www.andalus.org.uk/',
  'timetable_url': 'https://www.andalus.org.uk/',
  'source_type': 'dynamic_prayer_widget',
  'parser': None}]


def _flat_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    return re.sub(r"\s+", " ", " ".join(soup.stripped_strings)).strip()


def _fold(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(c for c in value if not unicodedata.combining(c))
    for mark in ("ʿ", "ʾ", "‘", "’", "`", "´"):
        value = value.replace(mark, "")
    return value


def _clock(raw: str | None) -> str | None:
    if not raw:
        return None
    value = " ".join(raw.strip().upper().split())
    for fmt in ("%I:%M %p", "%I:%M%p", "%H:%M"):
        try:
            return datetime.strptime(value, fmt).strftime("%H:%M")
        except ValueError:
            pass
    return None


TIME = r"(\d{1,2}:\d{2}\s*(?:AM|PM)?)"


def _empty() -> dict:
    return {name: None for name in PRAYERS}


def parse_huda(html: str, target: date) -> tuple[dict, dict]:
    text = _fold(_flat_html(html))
    marker = re.search(r"\btoday.?s\s+prayer\s+times\b", text, re.I)
    if not marker:
        raise ValueError("Al-Huda time section not found; site may now load times with JavaScript")
    region = text[marker.end():marker.end() + 1800].split("Annual timetable", 1)[0]
    published = re.search(r"\b(\d{1,2}/\d{1,2}/\d{4})\b", region)
    named = re.search(r"\b(\d{1,2}\s+[A-Za-z]+\s+\d{4})\b", region)
    if published:
        source_day = datetime.strptime(published.group(1), "%d/%m/%Y").date()
    elif named:
        source_day = datetime.strptime(named.group(1), "%d %B %Y").date()
    else:
        raise ValueError("Al-Huda page date not found")
    if source_day != target:
        raise ValueError(f"Al-Huda source date {source_day.isoformat()} differs from London date {target.isoformat()}")
    adhan, iqamah = _empty(), _empty()
    aliases = {"fajr": "Fajr", "dhuhr": "(?:Dhuhr|Dhuhur|Zuhr)", "asr": "Asr", "maghrib": "Maghrib", "isha": "Isha"}
    for key, label in aliases.items():
        match = re.search(rf"\b{label}\b\s+{TIME}.{{0,45}}?Jama.{{0,25}}?{TIME}", region, re.I)
        if match:
            adhan[key], iqamah[key] = _clock(match.group(1)), _clock(match.group(2))
    if sum(bool(x) for x in iqamah.values()) < 4:
        raise ValueError("Al-Huda parser found fewer than four iqamah times; page layout may have changed")
    return adhan, iqamah


def parse_sunnah(html: str, target: date) -> tuple[dict, dict]:
    text = _flat_html(html)
    section = re.search(r"Prayer Times\s+(.*?)\s+View Full Timetable", text, re.I)
    if not section:
        raise ValueError("Sunnah current prayer section not found")
    region = section.group(1)
    adhan, iqamah = _empty(), _empty()
    aliases = {"fajr": "Fajr", "dhuhr": "(?:Dhuhur|Dhuhr|Zuhr)", "asr": "Asr", "maghrib": "Maghrib", "isha": "Isha"}
    for key, label in aliases.items():
        found = re.search(rf"\b{label}\b\s+Begins:\s*{TIME}\s+Jamaat:\s*{TIME}", region, re.I)
        if found:
            adhan[key], iqamah[key] = _clock(found.group(1)), _clock(found.group(2))
    if sum(bool(x) for x in iqamah.values()) < 4:
        raise ValueError("Sunnah parser found fewer than four iqamah times")
    return adhan, iqamah


def parse_sunnah_dated(html: str, target: date) -> tuple[dict, dict]:
    """Accept Sunnah's daily widget ONLY when it prints today's full date.

    Their home-page summary has no effective date; some other pages embed a
    widget that says 'Salah Times 30 October 2026' followed by a prayer table.
    On Fridays the widget can show Jumuah rather than Dhuhr. We do not
    confuse Jumuah with an ordinary Dhuhr iqamah.
    """
    text = _flat_html(html)
    marker = re.search(r"\bSalah\s+Times\s+(\d{1,2}\s+[A-Za-z]+\s+\d{4})\b", text, re.I)
    if not marker:
        raise ValueError("Masjid Sunnah dated prayer widget not found")
    try:
        published = datetime.strptime(marker.group(1), "%d %B %Y").date()
    except ValueError as exc:
        raise ValueError("Masjid Sunnah date cannot be interpreted") from exc
    if published != target:
        raise ValueError(f"Masjid Sunnah widget is dated {published}, not {target}")
    region = text[marker.end():marker.end()+850]
    adhan, iqamah = _empty(), _empty()
    aliases = {"fajr":"Fajr", "dhuhr":"(?:Dhuhr|Dhuhur|Zuhr)",
               "asr":"Asr", "maghrib":"Maghrib", "isha":"Isha"}
    for prayer, label in aliases.items():
        match = re.search(rf"\b{label}\b\s+{TIME}\s+{TIME}", region, re.I)
        if match:
            adhan[prayer], iqamah[prayer] = _clock(match.group(1)), _clock(match.group(2))
    if sum(bool(value) for value in iqamah.values()) < 4:
        raise ValueError("Masjid Sunnah dated widget does not contain four Jamaat times")
    return adhan, iqamah


def last_sunday(year: int, month: int) -> date:
    following = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    d = following - timedelta(days=1)
    return d - timedelta(days=(d.weekday() + 1) % 7)


def _minutes(hhmm: str) -> int:
    h, m = [int(part) for part in hhmm.split(":")]
    return h * 60 + m


def parse_mwh(html: str, target: date) -> tuple[dict, dict]:
    """Parse MWHS monthly table, failing closed if DST calendar looks wrong.

    Example found on 2026-10-31: sunset was listed as 17:39 in a
    month grid that does not show the October clock rollback. We must not
    display that unverified civil time as current.
    """
    text = _flat_html(html)
    month = target.strftime("%B %Y")
    if month.lower() not in text.lower():
        raise ValueError("MWHS month on site differs from selected month")
    pattern = re.compile(r"\b(\d{1,2})\s+(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+" + (r"(\d{1,2}:\d{2})\s+" * 4) + r"(\d{1,2}:\d{2})\b", re.I)
    rows = {int(m.group(1)): list(m.groups()[2:7]) for m in pattern.finditer(text)}
    if target.day not in rows or len(rows) < 20:
        raise ValueError("MWHS complete daily timetable not found")
    # A change in UK civil clocks must be reflected in the published time.
    # If not, the site may show BST solar times after GMT begins (or vice versa).
    transition = last_sunday(target.year, 3 if target.month == 3 else 10) if target.month in (3, 10) else None
    if transition and transition.day > 1 and transition.day in rows and (transition.day - 1) in rows:
        before = _minutes(rows[transition.day - 1][3])  # Maghrib
        after = _minutes(rows[transition.day][3])
        shift = after - before
        if target.month == 10 and not (-75 <= shift <= -45):
            raise ValueError("MWHS published October grid may not account for BST to GMT change; verify with mosque")
        if target.month == 3 and not (45 <= shift <= 75):
            raise ValueError("MWHS published March grid may not account for GMT to BST change; verify with mosque")
    adhan = dict(zip(PRAYERS, rows[target.day]))
    iqamah = _empty()
    section = re.search(r"Iqama Times(.*?)(?:Jummah Prayer|Muslim Welfare House Sheffield|$)", text, re.I)
    if not section:
        raise ValueError("MWHS iqamah schedules not found")
    fragments = re.findall(r"Dates\s+(\d{1,2})\s*[-–]\s*(\d{1,2})(.*?)(?=Dates\s+\d{1,2}\s*[-–]|$)", section.group(1), re.I)
    matched = [part for start, end, part in fragments if int(start) <= target.day <= int(end)]
    if len(matched) != 1:
        raise ValueError("MWHS effective iqamah date range cannot be identified")
    for prayer, labels in {"fajr":"Fajr", "dhuhr":"Dhuhr", "asr":"Asr", "isha":"Isha"}.items():
        m = re.search(rf"\b{labels}\b\s+(\d{{1,2}}:\d{{2}})", matched[0], re.I)
        if m:
            iqamah[prayer] = _clock(m.group(1))
    if sum(bool(x) for x in iqamah.values()) < 3:
        raise ValueError("MWHS iqamah data incomplete")
    return adhan, iqamah


def parse_mwh_home(html: str, target: date) -> tuple[dict, dict]:
    """Read MWHS's *dated daily* home-page times, not its inconsistent month grid.

    As of October 2026 its /prayer-times monthly grid differs by an hour after
    the UK clock rollback. The home page publishes both adhan and iqamah for
    a named calendar day; reject it if that day is not the London calendar day.
    """
    text = _flat_html(html)
    header = re.search(
        r"Prayer Times for\s+(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+"
        r"(\d{1,2}\s+[A-Za-z]+\s+\d{4})\b", text, re.I
    )
    if not header:
        raise ValueError("MWHS dated daily prayer section not found")
    published = datetime.strptime(header.group(2), "%d %B %Y").date()
    if published != target or published.strftime("%a").lower() != header.group(1).lower():
        raise ValueError("MWHS homepage date differs from London today")
    # Limit to the prayer table. News, class times and event announcements must
    # not be interpreted as prayer times.
    end = re.search(r"\b(?:Upcoming Events|Latest Khutbahs)\b", text[header.end():], re.I)
    region = text[header.end():header.end()+end.start()] if end else text[header.end():header.end()+1400]
    adhan, iqamah = _empty(), _empty()
    for prayer in PRAYERS:
        found = re.search(
            rf"\b{prayer}\b\s+(\d{{1,2}}:\d{{2}})\s+"
            rf"Iqamah\s+(\d{{1,2}}:\d{{2}}|After Maghrib)", region, re.I
        )
        if found:
            adhan[prayer] = _clock(found.group(1))
            if found.group(2).lower() == "after maghrib":
                if prayer != 'isha':
                    raise ValueError('Unexpected combined Iqamah text')
            else:
                iqamah[prayer] = _clock(found.group(2))
    # In summer MWHS sometimes says "Iqamah After Maghrib" for Isha.
    # That is not a clock time; retain the other four verified prayers instead.
    if not all(adhan.values()) or sum(bool(x) for x in iqamah.values()) < 4:
        raise ValueError("MWHS daily iqamah values incomplete")
    return adhan, iqamah


def parse_industry(html: str, target: date) -> tuple[dict, dict]:
    """Industry Road's dated 'Today's Prayer Times' block.

    Its observed August page included an implausible Asr start (12:00 am).
    The shared sequence validator must reject that source rather than publish it.
    """
    text = _flat_html(html)
    marker = re.search(r"Today's Prayer Times", text, re.I)
    if not marker:
        raise ValueError("Industry Road dated prayer block not found")
    region = text[marker.end():marker.end()+750]
    date_match = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)\s+([A-Za-z]+)\s+(\d{4})\b", region, re.I)
    if not date_match:
        raise ValueError("Industry Road date missing")
    published = datetime.strptime(f"{date_match.group(1)} {date_match.group(2)} {date_match.group(3)}", "%d %B %Y").date()
    if published != target:
        raise ValueError("Industry Road date differs from London today")
    adhan, iqamah = _empty(), _empty()
    web_time = r"(\d{1,2}:\d{2}\s*(?:am|pm))"
    for prayer in PRAYERS:
        label = "(?:Dhuhr|Zuhr)" if prayer == 'dhuhr' else prayer
        match = re.search(rf"\b{label}\b\s+{web_time}\s+{web_time}", region, re.I)
        if match:
            adhan[prayer], iqamah[prayer] = _clock(match.group(1)), _clock(match.group(2))
    if adhan["asr"] == "00:00":
        # This official source has published midnight (12:00 am) as an
        # obviously invalid Asr beginning. Do not publish its Asr row,
        # but the remaining four rows can still be used if fully validated.
        adhan["asr"] = None
        iqamah["asr"] = None
    if sum(bool(x) for x in adhan.values()) < 4 or sum(bool(x) for x in iqamah.values()) < 4:
        raise ValueError("Industry Road daily time rows incomplete")
    return adhan, iqamah


def _day_cell_matches(value: str, target: date) -> bool:
    """Match a table's date cell, never accepting an unrelated day's rows."""
    value = " ".join(value.strip().split())
    if not value:
        return False
    candidates = [
        target.isoformat(),
        target.strftime("%d/%m/%Y"),
        target.strftime("%d-%m-%Y"),
        target.strftime("%d-%b-%Y"),
        target.strftime("%d %B %Y"),
        target.strftime("%d %b %Y"),
    ]
    if any(re.search(r"(?<!\d)" + re.escape(c) + r"(?!\d)", value, re.I) for c in candidates):
        return True
    # A bare day number is accepted only when the site's month/year heading
    # matches, and any printed weekday agrees with the target date.
    day = re.fullmatch(rf"0?{target.day}(?:\s+((?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)(?:day)?))?", value, re.I)
    if not day:
        return False
    return not day.group(1) or day.group(1)[:3].lower() == target.strftime("%a").lower()


def parse_mosque_times_tables(html: str, target: date) -> tuple[dict, dict]:
    """Read only explicitly dated rows from a mosque's published tables.

    Some mosqueprayertimes.org sites contain table HEADERS but no daily rows;
    these must stay unavailable. Never infer prayers from a location's solar
    timetable, or assume the first cell is today's day.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    # This is essential when the site renders '31 Sat' rather than '31/10/2026'.
    expected_month = target.strftime("%B")
    month_heading = re.search(r"\b([A-Za-z]+)\s+Prayers\s+Times\s*\(?\s*(\d{4})\s*\)?", text, re.I)
    month_verified = bool(month_heading and month_heading.group(1).lower() == expected_month.lower()
                          and month_heading.group(2) == str(target.year))
    if month_heading and not month_verified:
        raise ValueError("Official timetable month or year does not match Sheffield today")
    adhan, iqamah = _empty(), _empty()
    aliases = {"fajr": "fajr", "dhuhr": "(?:dhuhr|dhuhur|zuhr)", "asr": "asr",
               "maghrib": "maghrib", "isha": "(?:isha|ishaa)"}

    for table in soup.find_all("table"):
        trs = table.find_all("tr")
        if len(trs) < 2:
            continue
        for pos, tr in enumerate(trs[:-1]):
            heads = tr.find_all(["th", "td"], recursive=False)
            header = [re.sub(r"\s+", " ", cell.get_text(" ", strip=True)).strip().lower()
                      for cell in heads]
            if not header or not re.search(r"\bdate\b", header[0]):
                continue
            # Separate iqamah table or prayer-start table. Use only exact
            # clock columns for five named prayers, never sunrise/jumuah.
            colmap = {}
            for prayer, label in aliases.items():
                possible = [i for i, key in enumerate(header) if re.fullmatch(
                    rf"{label}(?:\s+iqamah|\s+jamaat|\s+jamah)?", key, re.I)]
                if len(possible) == 1:
                    colmap[prayer] = possible[0]
            if len(colmap) < 4:
                continue
            is_iqamah = sum("iqamah" in c or "jamaat" in c or "jamah" in c for c in header) >= 3
            # A table can contain multiple months; a fully dated row is allowed
            # even without a month heading. Bare numbers require that heading.
            for daily in trs[pos + 1:]:
                cells = daily.find_all(["th", "td"], recursive=False)
                if len(cells) <= max(colmap.values()):
                    continue
                date_str = cells[0].get_text(" ", strip=True)
                if not _day_cell_matches(date_str, target):
                    continue
                if (re.fullmatch(r"0?\d{1,2}(?:\s+\w+)?", date_str)
                    and not month_verified):
                    continue
                values = {}
                for prayer, index in colmap.items():
                    stamp = _clock(cells[index].get_text(" ", strip=True))
                    if stamp:
                        values[prayer] = stamp
                if len(values) < 4:
                    continue
                destination = iqamah if is_iqamah else adhan
                destination.update(values)
                break
    if sum(bool(v) for v in adhan.values()) < 4 or sum(bool(v) for v in iqamah.values()) < 4:
        raise ValueError("Official mosque timetable page has no matching dated prayer and Jamaat rows")
    return adhan, iqamah




def _parse_public_clock(segment: str) -> str | None:
    """Interpret a single Masjidbox visible time such as '5 10 AM' or '2:30 PM'.

    Do not use the city's calculated times; these values are attributed to the
    selected mosque profile. A missing/ambiguous time is not guessed.
    """
    match = re.search(
        r"(?<![\d])(?P<hour>\d{1,2})\s*(?:[:.]\s*|\s+)(?P<minute>\d{2})"
        r"(?:\s*(?P<period>a\.?m\.?|p\.?m\.?))?(?![\d])",
        segment, re.I,
    )
    if not match:
        return None
    hour = int(match.group('hour'))
    minute = int(match.group('minute'))
    if minute > 59:
        return None
    period = (match.group('period') or '').lower().replace('.', '')
    if period:
        if hour < 1 or hour > 12:
            return None
        hour = hour % 12 + (12 if period == 'pm' else 0)
    elif hour > 23:
        return None
    return f'{hour:02d}:{minute:02d}'


def parse_grand_masjidbox(html: str, target: date) -> tuple[dict, dict]:
    """Parse *complete prayer cards*, never countdown clocks or Jumuah rows.

    The earlier regex began at the first mention of 'Dhuhr' in a countdown
    header, sometimes collecting the Fajr time as Dhuhr. That produced the
    'Prayer starts are not in chronological order' error reported by GitHub.
    A valid card must be: <prayer> <clock> Iqamah <clock>.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    if not re.search(r"\bSheffield Grand Mosque\b", text, re.I):
        raise ValueError("Masjidbox mosque identity is not Sheffield Grand Mosque")
    if not re.search(r"\bGrimesthorpe\b", text, re.I):
        raise ValueError("Masjidbox mosque address could not be confirmed")
    header = text[:550]
    matched = re.search(
        r"\b(?P<weekday>Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+"
        r"(?P<month>January|February|March|April|May|June|July|August|September|October|November|December)"
        r"\s+(?P<day>\d{1,2}),?\s+(?P<year>20\d{2})\b", header, re.I,
    )
    if not matched:
        raise ValueError("Masjidbox public page has no visible English date")
    published = datetime.strptime(
        f"{matched['day']} {matched['month']} {matched['year']}", "%d %B %Y"
    ).date()
    if published != target:
        raise ValueError(f"Masjidbox page date {published} does not match {target}")
    if matched['weekday'].lower() != target.strftime('%A').lower():
        raise ValueError("Masjidbox page weekday disagrees with its date")

    # A prayer card is two adjacent clocks separated by the Iqamah label.
    # A countdown like 'The prayer of Dhuhr is in 04 Hours ...' cannot match.
    clock = r"(?:[01]?\d|2[0-3])(?:\s*[:.]\s*|\s+)[0-5]\d(?:\s*[AP]\.?M\.?)?"
    aliases = {"fajr": "Fajr", "dhuhr": "(?:Dhuhr|Zuhr|Dhuhur)",
               "asr": "Asr", "maghrib": "Maghrib", "isha": "(?:Isha|Ishaa)"}
    adhan, iqamah = _empty(), _empty()
    for prayer, alias in aliases.items():
        # Do not allow arbitrary text between the prayer name, time, and iqamah.
        pattern = rf"\b{alias}\b\s+(?P<start>{clock})\s+Iqamah\s+(?P<jam>{clock})(?=\s|$)"
        rows = list(re.finditer(pattern, text, re.I))
        if len(rows) != 1:
            continue  # Multiple conflicting matches also fail closed.
        begins = _parse_public_clock(rows[0]['start'])
        congregation = _parse_public_clock(rows[0]['jam'])
        if begins and congregation:
            adhan[prayer], iqamah[prayer] = begins, congregation
    if sum(bool(iqamah[p]) for p in PRAYERS) < 4:
        raise ValueError("Masjidbox public page does not expose four complete dated Jamaat cards")
    return adhan, iqamah


def parse_makki_masjidbox(html: str, target: date) -> tuple[dict, dict]:
    """Parse *complete prayer cards*, never countdown clocks or Jumuah rows.

    The earlier regex began at the first mention of 'Dhuhr' in a countdown
    header, sometimes collecting the Fajr time as Dhuhr. That produced the
    'Prayer starts are not in chronological order' error reported by GitHub.
    A valid card must be: <prayer> <clock> Iqamah <clock>.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    if not re.search(r"\bMakki Mosque Sheffield\b", text, re.I):
        raise ValueError("Masjidbox mosque identity is not Makki Mosque Sheffield")
    if not re.search(r"\bPlantation Road\b", text, re.I):
        raise ValueError("Masjidbox mosque address could not be confirmed")
    header = text[:550]
    matched = re.search(
        r"\b(?P<weekday>Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+"
        r"(?P<month>January|February|March|April|May|June|July|August|September|October|November|December)"
        r"\s+(?P<day>\d{1,2}),?\s+(?P<year>20\d{2})\b", header, re.I,
    )
    if not matched:
        raise ValueError("Masjidbox public page has no visible English date")
    published = datetime.strptime(
        f"{matched['day']} {matched['month']} {matched['year']}", "%d %B %Y"
    ).date()
    if published != target:
        raise ValueError(f"Masjidbox page date {published} does not match {target}")
    if matched['weekday'].lower() != target.strftime('%A').lower():
        raise ValueError("Masjidbox page weekday disagrees with its date")

    # A prayer card is two adjacent clocks separated by the Iqamah label.
    # A countdown like 'The prayer of Dhuhr is in 04 Hours ...' cannot match.
    clock = r"(?:[01]?\d|2[0-3])(?:\s*[:.]\s*|\s+)[0-5]\d(?:\s*[AP]\.?M\.?)?"
    aliases = {"fajr": "Fajr", "dhuhr": "(?:Dhuhr|Zuhr|Dhuhur)",
               "asr": "Asr", "maghrib": "Maghrib", "isha": "(?:Isha|Ishaa)"}
    adhan, iqamah = _empty(), _empty()
    for prayer, alias in aliases.items():
        # Do not allow arbitrary text between the prayer name, time, and iqamah.
        pattern = rf"\b{alias}\b\s+(?P<start>{clock})\s+Iqamah\s+(?P<jam>{clock})(?=\s|$)"
        rows = list(re.finditer(pattern, text, re.I))
        if len(rows) != 1:
            continue  # Multiple conflicting matches also fail closed.
        begins = _parse_public_clock(rows[0]['start'])
        congregation = _parse_public_clock(rows[0]['jam'])
        if begins and congregation:
            adhan[prayer], iqamah[prayer] = begins, congregation
    if sum(bool(iqamah[p]) for p in PRAYERS) < 4:
        raise ValueError("Masjidbox public page does not expose four complete dated Jamaat cards")
    return adhan, iqamah


def parse_baitul_dated(html: str, target: date) -> tuple[dict, dict]:
    """Accept the official mosque's Start/Iqamah grid ONLY with a clear date.

    The website currently shows 'Today's Prayers' but search caches contain
    older values. We must not assume that an undated grid represents today.
    """
    text = _flat_html(html)
    if not re.search(r"Baitul\s+Mukarram", text[:1800], re.I):
        raise ValueError("Baitul Mukarram identity not confirmed")
    match = re.search(r"Today[’']?s\s+Prayers", text, re.I)
    if not match:
        raise ValueError("Baitul Mukarram official daily prayer table not found")
    nearby = text[max(0, match.start()-120):match.end()+230]
    dates = re.findall(r"\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4}|\d{1,2}\s+[A-Za-z]+\s+20\d{2}|[A-Za-z]+\s+\d{1,2},?\s+20\d{2})\b", nearby)
    parsed = set()
    for value in dates:
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d %B %Y", "%d %b %Y", "%B %d, %Y", "%B %d %Y", "%b %d, %Y"):
            try:
                parsed.add(datetime.strptime(value, fmt).date())
                break
            except ValueError:
                pass
    if parsed != {target}:
        raise ValueError("Baitul Mukarram shows no unambiguous date matching London today")
    region = text[match.end():match.end()+1300].split('Jumu',1)[0]
    adhan, iqamah = _empty(), _empty()
    arabic = {"fajr":"الفجر", "dhuhr":"الظهر", "asr":"العصر", "maghrib":"المغرب", "isha":"العشاء"}
    aliases = {"fajr":"Fajr", "dhuhr":"(?:Dhuhr|Zuhr)", "asr":"Asr", "maghrib":"Maghrib", "isha":"(?:Isha|Ishaa)"}
    for prayer, label in aliases.items():
        pat = rf"\b{label}\b\s+(?:{arabic[prayer]}\s+)?{TIME}\s+{TIME}"
        matches = list(re.finditer(pat, region, re.I))
        if len(matches)==1:
            adhan[prayer], iqamah[prayer] = _clock(matches[0].group(1)), _clock(matches[0].group(2))
    if sum(bool(v) for v in iqamah.values()) < 4:
        raise ValueError("Baitul Mukarram dated grid lacks four Iqamah rows")
    return adhan, iqamah


def parse_umar_independent_monthly(html: str, target: date) -> tuple[dict, dict]:
    """Third-party Masjid247 month grid, strictly mosque/month/day-specific.

    Some monthly grids intentionally have no Maghrib 'begins' time; preserve
    that gap rather than inventing it from astronomical calculations.
    """
    soup = BeautifulSoup(html, 'html.parser')
    for tag in soup(['script','style','noscript','svg']):
        tag.decompose()
    text = re.sub(r'\s+', ' ', soup.get_text(' ', strip=True))
    headline = re.search(r'\bMasjid Umar Sheffield\s+Prayer Timetable\s*[-–—:]\s*'
                         r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+(20\d{2})\b', text, re.I)
    if not headline:
        raise ValueError('Masjid Umar independent monthly timetable identity/date heading missing')
    if headline.group(1).lower()!=target.strftime('%B').lower() or int(headline.group(2))!=target.year:
        raise ValueError('Masjid Umar independent month/year does not match London today')
    matched = []
    alias = {'fajr':'fajr','dhuhr':'dhuhr','asr':'asr','maghrib':'maghrib','isha':'isha'}
    for table in soup.find_all('table'):
        trs = table.find_all('tr')
        if len(trs)<2:
            continue
        for headpos, tr in enumerate(trs[:-1]):
            headers = [re.sub(r'\s+', ' ', c.get_text(' ',strip=True)).strip().lower()
                       for c in tr.find_all(['th','td'], recursive=False)]
            if not headers or headers[0] != 'date':
                continue
            columns = {}
            for prayer in PRAYERS:
                for target_part, pattern in [('adhan',rf'^{prayer}\s+(?:begins|begin|start)$'),
                                             ('iqamah',rf'^{prayer}\s+(?:jamat|jamaat|jamah|iqamah)$')]:
                    indexes=[i for i,h in enumerate(headers) if re.fullmatch(pattern,h,re.I)]
                    if len(indexes)==1:
                        columns[(prayer,target_part)] = indexes[0]
            if len([p for p in PRAYERS if (p,'iqamah') in columns])<4:
                continue
            for daily in trs[headpos+1:]:
                cells=daily.find_all(['th','td'], recursive=False)
                if not cells or not _day_cell_matches(cells[0].get_text(' ',strip=True),target):
                    continue
                adhan, iqamah=_empty(),_empty()
                for (prayer, group), index in columns.items():
                    if index>=len(cells):
                        continue
                    value=_clock(cells[index].get_text(' ',strip=True))
                    (adhan if group=='adhan' else iqamah)[prayer]=value
                matched.append((adhan, iqamah))
    if len(matched)!=1:
        raise ValueError('Masjid Umar independent source has no unique row for London today')
    adhan,iqamah=matched[0]
    if sum(bool(x) for x in iqamah.values())<4:
        raise ValueError('Masjid Umar independent row lacks four Jamaat times')
    return adhan,iqamah


# Independent directories are optional date-checked fallbacks only. They are
# *not* official mosque confirmations or substitutes for inaccessible APIs.
INDEPENDENT_SOURCES = {
    "grand": (
        ("faseela", "https://www.faseela.org/sheffield/sheffield-grand-mosque-emaan"),
        ("city_listing", "https://prayer-times.co.uk/sheffield"),
    ),
    "madina": (
        ("faseela", "https://www.faseela.org/sheffield/madina-masjid"),
        ("city_listing", "https://prayer-times.co.uk/sheffield"),
    ),
    "umar": (
        ("masjid247", "https://www.masjid247.com/prayertimes/gbr/sheffield/masjid-umar-sheffield/monthly/2176"),
    ),
    "andalus": (
        # Independent mosque-specific page: date and congregation rows REQUIRED.
        # The official Andalus homepage currently loads its times in JavaScript.
        ("prayersconnect", "https://prayersconnect.com/mosques/82643226-andalus-community-center-sheffield-england-united-kingdom"),
    ),
}


def parse_andalus_prayersconnect(html: str, target: date) -> tuple[dict, dict]:
    """Parse a *dated* independent Andalus mosque entry, never city calculations.

    Fail closed if the website returns a loading-only template, a stale date,
    another mosque's schedule, or a table without 5 complete prayer+iqamah
    pairs. This directory is NOT the mosque's official timetable.
    """
    text = _flat_html(html)
    text = re.sub(r"[\u200e\u200f\u202a-\u202e]", "", text)
    identity = text[:1800]
    if not re.search(r"\bAndalus Community Cent(?:er|re)\b", identity, re.I):
        raise ValueError("Andalus directory page identity does not match the centre")
    if not re.search(r"43\s+Townhead\s+(?:St(?:reet)?\b)", identity, re.I) or not re.search(r"\bSheffield\b", identity, re.I):
        raise ValueError("Andalus directory page address is not 43 Townhead Street, Sheffield")
    schedule = re.search(r"\bPrayers\s+Schedule\b", text, re.I)
    if not schedule:
        raise ValueError("Andalus directory has no prayer schedule")
    region = text[schedule.end():schedule.end()+1800]
    dated = re.search(
        r"\b(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+"
        r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+"
        r"(\d{1,2}),?\s+(20\d{2})\b", region, re.I,
    )
    if not dated:
        raise ValueError("Andalus independent schedule has no explicit day, month and year")
    published = datetime.strptime(
        f"{dated.group(3)} {dated.group(2)} {dated.group(4)}", "%d %B %Y"
    ).date()
    if published != target or dated.group(1).lower() != target.strftime('%A').lower():
        raise ValueError(f"Andalus directory date {published} is not Sheffield today {target}")
    region = region[dated.end():]
    headings = re.search(r"\bPrayer\s+Name\s+Prayer\s+Time\s+Iqamah\s+Time\b", region, re.I)
    if not headings:
        raise ValueError("Andalus independent table has no prayer and iqamah columns")
    region = region[headings.end():]
    region = re.split(r"\b(?:Verified|Prediction|Unknown|Events in Mosque|Donate us)\b", region, maxsplit=1, flags=re.I)[0]
    clock = r"(\d{1,2}:\d{2}\s*(?:AM|PM))"
    labels = {"fajr": "Fajr", "dhuhr": "(?:Dhuhr|Zuhr)", "asr": "Asr",
              "maghrib": "Maghrib", "isha": "(?:Isha|Ishaa)"}
    adhan, iqamah = _empty(), _empty()
    for prayer, label in labels.items():
        # Arabic labels may appear between the English name and the clocks.
        # Both clocks must be adjacent; a header/countdown cannot match.
        regex = rf"(?<![A-Za-z])(?:{label})\b[^\d]{{0,35}}?{clock}\s+{clock}(?=\s|$)"
        matches = list(re.finditer(regex, region, re.I))
        if len(matches) != 1:
            raise ValueError(f"Andalus independent table has no unique {prayer} prayer and iqamah pair")
        start, jam = _clock(matches[0].group(1)), _clock(matches[0].group(2))
        if not start or not jam:
            raise ValueError(f"Andalus independent time format invalid for {prayer}")
        adhan[prayer], iqamah[prayer] = start, jam
    return adhan, iqamah


def parse_faseela_dated(html: str, target: date, mosque_id: str) -> tuple[dict, dict]:
    """Require mosque identity and date, then read only Time/Jamaat columns."""
    if mosque_id not in ("grand", "madina"):
        raise ValueError("No independently tracked Faseela mosque profile")
    text = _flat_html(html)
    identity = r"Sheffield Grand Mosque" if mosque_id == "grand" else r"Madina Masjid"
    if not re.search(identity, text[:1500], re.I):
        raise ValueError("Faseela mosque identity differs from selected Sheffield mosque")
    date_marker = re.search(r"(?<!\d)(\d{2}/\d{2}/20\d{2})\s*\((Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\)", text[:1500], re.I)
    if not date_marker:
        raise ValueError("Faseela timetable has no unambiguous dated heading")
    published = datetime.strptime(date_marker[1], "%d/%m/%Y").date()
    if published != target or date_marker[2].lower() != target.strftime('%A').lower():
        raise ValueError(f"Faseela timetable date {published} differs from {target}")
    # Never read 'Tomorrow's Jamaat' as today's Jamaat.
    region = text[date_marker.end():date_marker.end()+950]
    if not re.search(r"\bPrayer\s+Time\s+Jamaat\b", region, re.I):
        raise ValueError("Faseela current prayer table headings missing")
    adhan, iqamah = _empty(), _empty()
    for prayer, label in {"fajr": "Fajr", "dhuhr": "(?:Zuhr|Dhuhr)",
                          "asr": "Asr", "maghrib": "Maghrib", "isha": "Isha"}.items():
        match = re.search(rf"\b{label}\b\s+(\d{{1,2}}:\d{{2}})\s+(\d{{1,2}}:\d{{2}})(?=\s|$)", region, re.I)
        if match:
            adhan[prayer], iqamah[prayer] = _clock(match[1]), _clock(match[2])
    if sum(bool(x) for x in iqamah.values()) < 4:
        raise ValueError("Faseela has fewer than four dated Jamaat times")
    return adhan, iqamah


def parse_city_mosque_jamaat(html: str, target: date, mosque_id: str) -> tuple[dict, dict]:
    """Use ONLY the dated mosque-specific Jamaat table, not city starts.

    The city page also lists calculated astronomical starts. The two are
    separate sections and must never be conflated.
    """
    text = _flat_html(html)
    label = {"grand": "Sheffield Grand Mosque",
             "madina": "Madina Masjid (Wolseley Road)"}.get(mosque_id)
    if not label:
        raise ValueError("No matching Sheffield congregation directory entry")
    heading = re.search(r"Jama[’'`]?ah\s+times\s+today\s+at\s+Sheffield\s+mosques", text, re.I)
    if not heading:
        raise ValueError("City's mosque congregation table is missing")
    region = text[heading.end():heading.end()+2400]
    date_label = (rf"{re.escape(target.strftime('%A'))},?\s+0?{target.day}"
                  rf"(?:st|nd|rd|th)?\s+{re.escape(target.strftime('%B'))}\s+{target.year}")
    if not re.search(rf"Congregation\s+\(iqamah\)\s+times\s+for\s+{date_label}", region, re.I):
        raise ValueError("City listing is not dated for Sheffield today")
    # Do not match directory cards or the general city astronomical timetable.
    region = re.split(r"\bMosques in Sheffield\b", region, maxsplit=1, flags=re.I)[0]
    clock = r"([01]?\d|2[0-3]):([0-5]\d)"
    stamp = r"((?:[01]?\d|2[0-3]):[0-5]\d)"
    pat = re.escape(label) + r"\s+" + r"\s+".join([stamp] * 5) + r"(?=\s|$)"
    found = re.search(pat, region, re.I)
    if not found:
        raise ValueError("City listing has no complete mosque-specific Jamaat row")
    iqamah = {prayer: _clock(raw) for prayer, raw in zip(PRAYERS, found.groups())}
    return _empty(), iqamah


def validate_independent_times(adhan: dict, iqamah: dict) -> None:
    """Check today's third-party values without inventing adhan start times."""
    if sum(bool(t) for t in iqamah.values()) < 4:
        raise ValueError("Independent listing has fewer than four Jamaat times")
    for prayer in PRAYERS:
        start, jam = adhan.get(prayer), iqamah.get(prayer)
        if start and _clock(start) != start:
            raise ValueError(f"Bad independent prayer start: {prayer}")
        if jam and _clock(jam) != jam:
            raise ValueError(f"Bad independent Jamaat: {prayer}")
        if start and jam and _minutes(jam) < _minutes(start):
            raise ValueError(f"Independent Jamaat before prayer starts: {prayer}")
    for group in (adhan, iqamah):
        times = [_minutes(group[p]) for p in PRAYERS if group.get(p)]
        if any(b <= a for a, b in zip(times, times[1:])):
            raise ValueError("Independent prayer times are out of sequence")


def _independent_or_manual(row: dict, mosque: dict, target: date) -> dict:
    """Prefer an administrator-confirmed row over independent directories."""
    failures = []
    for provider, url in INDEPENDENT_SOURCES.get(mosque['id'], ()):
        try:
            html = _official_html(url)
            if provider == 'faseela':
                adhan, iqamah = parse_faseela_dated(html, target, mosque['id'])
            elif provider == 'masjid247':
                adhan, iqamah = parse_umar_independent_monthly(html, target)
            elif provider == 'prayersconnect':
                adhan, iqamah = parse_andalus_prayersconnect(html, target)
            elif provider == 'city_listing':
                adhan, iqamah = parse_city_mosque_jamaat(html, target, mosque['id'])
            else:
                raise ValueError('Unrecognized independent provider')
            validate_independent_times(adhan, iqamah)
            provisional = _initial_record(mosque)
            provisional.update(
                adhan=adhan, iqamah=iqamah,
                status=('third_party_dated' if all(iqamah.values()) else 'third_party_partial'),
                source_date=target.isoformat(), checked_at=datetime.now(TZ).isoformat(timespec='seconds'),
                updated_at=datetime.now(TZ).isoformat(timespec='seconds'),
                source_type='third_party_dated_listing', timetable_url=url,
                note='مواعيد مؤرخة من دليل مستقل وليست تأكيدًا من إدارة المسجد؛ يرجى مراجعة المسجد قبل الاعتماد عليها.',
                provenance='Independent, dated third-party listing; not confirmed by mosque',
            )
            return _manual_or_row(provisional, mosque, target)
        except (requests.RequestException, ValueError, KeyError, RuntimeError) as exc:
            failures.append(f'{provider}: {type(exc).__name__}: {str(exc)[:92]}')
    if failures:
        prior = row.get('diagnostic', '')
        row['diagnostic'] = (prior + ' | Independent: ' + ' | '.join(failures))[:550]
    return _manual_or_row(row, mosque, target)


def validate_times(adhan: dict, iqamah: dict) -> None:
    """Reject obvious HTML parsing errors instead of publishing odd times."""
    for prayer in PRAYERS:
        begins, congregation = adhan.get(prayer), iqamah.get(prayer)
        if (begins and _clock(begins) != begins) or (congregation and _clock(congregation) != congregation):
            raise ValueError(f"Invalid clock string for {prayer}")
        if congregation and not begins:
            raise ValueError(f"Iqamah without published adhan for {prayer}")
        if begins and congregation and _minutes(congregation) < _minutes(begins):
            raise ValueError(f"Iqamah before prayer begins for {prayer}")
    values = [adhan[p] for p in PRAYERS if adhan[p]]
    if len(values) >= 4 and any(_minutes(b) <= _minutes(a) for a, b in zip(values, values[1:])):
        raise ValueError("Prayer starts are not in chronological order")


PARSERS: dict[str, Callable[[str, date], tuple[dict, dict]]] = {
    "huda": parse_huda,
    "sunnah": parse_sunnah,
    "mwh_home": parse_mwh_home,
    "industry": parse_industry,
    "mosque_times": parse_mosque_times_tables,
    "grand_masjidbox": parse_grand_masjidbox,
    "makki_masjidbox": parse_makki_masjidbox,
    "baitul_dated": parse_baitul_dated,
}


def _official_html(url: str) -> str:
    """Fetch HTTPS official page, permitting only safe same-domain redirects.

    The old collector rejected even a normal / -> /home HTTP 301. This helper
    allows up to 3 HTTPS redirects on the same registered host or its www alias.
    It never follows a redirect to a different domain or a local network host.
    """
    origin = urlsplit(url)
    expected_host = (origin.hostname or "").lower().removeprefix("www.")
    if origin.scheme != "https" or not expected_host:
        raise ValueError("Official source URL is not an HTTPS website")
    current = url
    visited = set()
    for _ in range(4):
        if current in visited:
            raise ValueError("Source has a redirect loop")
        visited.add(current)
        response = requests.get(
            current, timeout=(5, 12), allow_redirects=False,
            headers={
                "User-Agent": os.getenv("PORTAL_USER_AGENT", "SheffieldMasjidPortal/1.0 (public timetable checker)"),
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-GB,en;q=0.9",
                "Cache-Control": "no-cache",
            },
        )
        if response.status_code in (301, 302, 303, 307, 308):
            location = response.headers.get("Location")
            if not location:
                raise ValueError(f"Source returned HTTP {response.status_code} without redirect destination")
            target_url = urljoin(current, location)
            target = urlsplit(target_url)
            if (target.scheme != "https" or (target.hostname or "").lower().removeprefix("www.") != expected_host
                    or target.username is not None or target.password is not None
                    or target.port not in (None, 443)):
                raise ValueError("Source redirected to a different domain or non-HTTPS URL")
            current = target_url
            continue
        if response.status_code != 200:
            raise ValueError(f"Official source returned HTTP {response.status_code}")
        if len(response.content) > 2_000_000:
            raise ValueError("Source HTML unexpectedly large")
        content_type = response.headers.get("Content-Type", "text/html").split(";", 1)[0].strip().lower()
        if content_type not in ("text/html", "application/xhtml+xml"):
            raise ValueError(f"Official source returned {content_type} instead of HTML")
        return response.text
    raise ValueError("Official source redirected too many times")


def _initial_record(mosque: dict) -> dict:
    row = {k: v for k, v in mosque.items() if k != "parser"}
    row.update(
        adhan=_empty(), iqamah=_empty(), status="not_connected",
        source_date=None, checked_at=None, updated_at=None, note=None,
    )
    return row


# Official Andalus daily widget is populated by client-side JavaScript. A
# normal requests.get() response contains "Loading", even when the public site
# shows five complete prayer and Iqamah rows in a real browser.
ANDALUS_OFFICIAL_URL = "https://www.andalus.org.uk/"


def parse_andalus_rendered(html: str, target: date) -> tuple[dict, dict]:
    """Accept only five complete pairs from the CURRENT dated official widget.

    This parser intentionally has no fallback to city-wide calculated prayer
    times and never guesses the year from a historic PDF or stale daily row.
    """
    text = _flat_html(html)
    header = re.search(r"Today[’']s\s+Prayer\s+Times\b", text, re.I)
    if not header:
        raise ValueError("Andalus rendered page has no Today's Prayer Times widget")
    region = text[header.end():header.end()+1500]
    day_marker = re.search(
        r"\b(Mon(?:day)?|Tue(?:sday)?|Wed(?:nesday)?|Thu(?:rsday)?|Fri(?:day)?|Sat(?:urday)?|Sun(?:day)?)"
        r"\s*,?\s*0?(\d{1,2})\s+"
        r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\b",
        region[:280], re.I,
    )
    if not day_marker:
        raise ValueError("Andalus widget doesn't expose a weekday/day/month for today's times")
    day_name, dd, month_name = day_marker.groups()
    if not (day_name.lower()[:3] == target.strftime('%a').lower()
            and int(dd) == target.day
            and month_name.lower()[:3] == target.strftime('%b').lower()):
        raise ValueError(f"Andalus widget is dated {day_name} {dd} {month_name}, not {target.isoformat()}")
    # Stay strictly inside this day's prayer table; avoid 'Next Prayer',
    # Jumu'ah notices and footer entries with additional clock readings.
    region = re.split(r"\bJumu[’']?ah\s+Friday\b|\bYears\s+Serving\b", region, maxsplit=1, flags=re.I)[0]
    labels = {
        'fajr': r'\bFajr\b', 'dhuhr': r'\bDhuhr\b',
        'asr': r'\bAsr\b', 'maghrib': r'\bMaghrib\b', 'isha': r'\bIsha\b',
    }
    spans = []
    for prayer in PRAYERS:
        matches = list(re.finditer(labels[prayer], region, re.I))
        if len(matches) != 1:
            raise ValueError(f"Andalus has {len(matches)} labels for {prayer}; expected one")
        spans.append((prayer, matches[0].start(), matches[0].end()))
    if [x[1] for x in spans] != sorted(x[1] for x in spans):
        raise ValueError("Andalus prayers are not in Fajr-to-Isha order")
    adhan, iqamah = _empty(), _empty()
    clock_re = r'(?<!\d)(\d{1,2}:\d{2}\s*(?:AM|PM))\b'
    for idx, (prayer, _start, end) in enumerate(spans):
        next_start = spans[idx+1][1] if idx+1 < len(spans) else len(region)
        cell = region[end:next_start]
        clocks = re.findall(clock_re, cell, re.I)
        if len(clocks) != 2 or not re.search(r'\bIqam(?:a|ah)\b', cell, re.I):
            raise ValueError(f"Andalus {prayer}: need two times and Iqamah label")
        start, jamaat = (_clock(x) for x in clocks)
        if start is None or jamaat is None:
            raise ValueError(f"Andalus {prayer}: invalid clock")
        adhan[prayer], iqamah[prayer] = start, jamaat
    validate_times(adhan, iqamah)
    return adhan, iqamah


def _render_andalus_homepage() -> str:
    """Run a locally installed Chrome/Chromium to render the public page.

    ubuntu-latest GitHub-hosted runners usually include Google Chrome. No API
    key, third-party proxy, Selenium dependency, or browser credential needed.
    Any failure is treated as unavailable, never as a reason to invent times.
    """
    browser = next((shutil.which(name) for name in
                    ('google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser')
                    if shutil.which(name)), None)
    if not browser:
        raise RuntimeError("No Chrome/Chromium browser installed on the GitHub runner")
    cmd = [browser, '--headless=new', '--no-sandbox', '--disable-gpu',
           '--disable-dev-shm-usage', '--no-first-run', '--no-default-browser-check',
           '--lang=en-GB', '--virtual-time-budget=14000', '--dump-dom',
           ANDALUS_OFFICIAL_URL]
    environment = os.environ.copy()
    environment['TZ'] = 'Europe/London'
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=35,
                                env=environment, check=False)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Chrome timed out rendering Andalus page") from exc
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError(f"Chrome failed to render Andalus: exit {result.returncode}")
    if len(result.stdout) > 4_000_000:
        raise ValueError("Andalus rendered page was unexpectedly large")
    return result.stdout


def _andalus_dated_screenshot(target: date) -> dict | None:
    """31 October 2026 user-supplied screenshot. Never apply to later dates.

    Screenshot is a dated observation of the official public website, not a
    continuously fetched feed or an assertion of mosque administration approval.
    """
    if target != date(2026, 10, 31):
        return None
    mosque = next(m for m in MOSQUES if m['id'] == 'andalus')
    record = _initial_record(mosque)
    record.update(
        adhan=dict(zip(PRAYERS, ('05:11', '11:50', '14:07', '16:39', '18:29'))),
        iqamah=dict(zip(PRAYERS, ('06:00', '12:30', '14:45', '16:44', '19:00'))),
        source_type='dated_website_screenshot', status='manual_dated',
        source_date=target.isoformat(),
        checked_at='2026-10-31T14:56:00+00:00',
        updated_at='2026-10-31T14:56:00+00:00',
        timetable_url=ANDALUS_OFFICIAL_URL,
        note=('31 Oct 2026: times transcribed from a visitor-provided screenshot '
              'of the official Andalus prayer timetable. Not a live feed; '
              'confirm any subsequent timetable changes with the centre.'),
        provenance='Screenshot of Andalus official site shared on 2026-10-31',
    )
    validate_times(record['adhan'], record['iqamah'])
    return record


def _read_andalus_official(mosque: dict, target: date) -> dict:
    record = _initial_record(mosque)
    record['checked_at'] = datetime.now(TZ).isoformat(timespec='seconds')
    try:
        html = _render_andalus_homepage()
        adhan, iqamah = parse_andalus_rendered(html, target)
        record.update(adhan=adhan, iqamah=iqamah, status='updated',
                      source_type='official_rendered_daily_widget',
                      source_date=target.isoformat(),
                      updated_at=record['checked_at'],
                      timetable_url=ANDALUS_OFFICIAL_URL,
                      note='Five daily Adhan and Iqamah rows read from the official Andalus website using a JavaScript-capable browser.')
        return record
    except (RuntimeError, ValueError, OSError) as exc:
        detail = f'{type(exc).__name__}: {str(exc)[:160]}'
        LOG.warning('Andalus rendered prayer widget unavailable: %s', detail)
        screenshot = _andalus_dated_screenshot(target)
        if screenshot:
            screenshot['diagnostic'] = f'Automatic website extraction unavailable: {detail}'
            return screenshot
        record['note'] = 'Official Andalus website displays a dynamic timetable, but this run could not read today’s five dated prayer/Iqamah pairs.'
        record['diagnostic'] = detail
        return _independent_or_manual(record, mosque, target)


def _read_official(mosque: dict, target: date) -> dict:
    if mosque["id"] == "andalus":
        return _read_andalus_official(mosque, target)
    row = _initial_record(mosque)
    if not mosque["parser"]:
        row["note"] = ("لا يعرض موقع الأندلس مواقيت مؤرخة قابلة للقراءة الآلية حاليًا؛ يوجد رابط رسمي ومحاولة قراءة دليل مستقل مؤرخ."
                       if mosque["id"] == "andalus" else
                       "لا تنشر صفحة دليل مسجد قباء جدولًا مؤرخًا للإقامة؛ نعرض الرابط والموقع فقط حتى يتوفر جدول معتمد."
                       if mosque["id"] == "quba" else
                       "هذه الصفحة دليل غير رسمي، ولا تؤكد أوقات الإقامة؛ اطلب جدول الجماعة من المسجد."
                       if mosque["id"] == "risalah" else
                       "هذا المصدر غير مربوط آليًا بعد؛ تحقق من موقع المسجد أو جدوله الرسمي.")
        if mosque["id"] in INDEPENDENT_SOURCES:
            return _independent_or_manual(row, mosque, target)
        return _manual_or_row(row, mosque, target)
    row["checked_at"] = datetime.now(TZ).isoformat(timespec="seconds")
    if mosque["id"] == "sunnah":
        # These are explicit OFFICIAL daily widgets. A dated row on the home
        # page is not guaranteed; try the known daily widget surfaces first.
        for dated_url in ("https://masjidsunnahsheffield.co.uk/about/",
                          "https://masjidsunnahsheffield.co.uk/contact/"):
            try:
                dated_html = _official_html(dated_url)
                adhan, iqamah = parse_sunnah_dated(dated_html, target)
                validate_times(adhan, iqamah)
                row["adhan"], row["iqamah"] = adhan, iqamah
                row["status"] = "updated" if all(iqamah.values()) else "partial"
                row["source_date"] = target.isoformat()
                row["timetable_url"] = dated_url
                row["updated_at"] = row["checked_at"]
                if row["status"] == "partial":
                    row["note"] = "Official dated widget omits some prayers; Jumuah is not treated as daily Dhuhr."
                return row
            except (requests.RequestException, ValueError, RuntimeError) as exc:
                LOG.info("Sunnah dated widget unavailable (%s): %s", dated_url, exc)
    try:
        html = _official_html(mosque["timetable_url"])
        adhan, iqamah = PARSERS[mosque["parser"]](html, target)
        validate_times(adhan, iqamah)
        row["adhan"], row["iqamah"] = adhan, iqamah
        if mosque["parser"] == "sunnah":
            # The homepage shows five rows but no visible applicable date.
            # Do not call these today's confirmed times.
            row["status"] = "undated"
            row["note"] = "مواعيد من الموقع الرسمي، لكن تاريخ سريانها غير ظاهر؛ يرجى التأكد من المسجد."
        else:
            row["status"] = "updated" if all(iqamah.values()) else "partial"
            row["source_date"] = target.isoformat()
            if row["status"] == "partial":
                row["note"] = "بعض مواعيد الإقامة غير منشورة كوقت محدد؛ لم نخمنها."
                if mosque["parser"] == "mwh_home" and re.search(r"Iqamah\s+After Maghrib", html, re.I):
                    row["note"] = "موقع المسجد يذكر أن إقامة العشاء بعد المغرب دون ساعة محددة؛ لم نخمن وقتها."
                if mosque["parser"] == "industry" and not iqamah.get("asr"):
                    row["note"] = "وقت بداية العصر المنشور غير صحيح (منتصف الليل)؛ أخفينا العصر وعرضنا بقية الأوقات المؤرخة."
        if mosque["parser"] == "makki_masjidbox":
            row["note"] = "Dated Makki Mosque Masjidbox page linked from its official website; verify with mosque if travelling."
        if mosque["parser"] == "grand_masjidbox":
            row["note"] = ("Public Masjidbox daily timetable for Sheffield Grand Mosque; "
                           "the mosque should confirm that this is their current managed profile."
                           + (" Some prayer rows were unavailable and left blank." if row["status"] == "partial" else ""))
        row["updated_at"] = row["checked_at"]  # Compatibility with older UI.
    except (requests.RequestException, ValueError, RuntimeError, KeyError) as exc:
        if mosque["id"] == "huda":
            # The archived PDF row is only used when THIS EXACT DATE was
            # independently confirmed. A source HTTP 403, timeout, or page
            # change should not destroy a separately verified same-day row.
            try:
                return _huda_pdf_fallback(mosque, target)
            except (ValueError, KeyError, OSError, json.JSONDecodeError) as fallback_exc:
                LOG.warning("Al-Huda PDF cannot be used for this date: %s", fallback_exc)
                original_failure = f"{exc}; verified PDF fallback unavailable: {fallback_exc}"
        else:
            original_failure = str(exc)
        LOG.warning("Unable to verify source %s: %s", mosque["id"], original_failure)
        if mosque["parser"] == "mosque_times":
            row["status"] = "not_connected"
            row["note"] = "The mosque timetable page could not supply dated Jamaat rows; please ask the mosque for a dated timetable."
        else:
            row["status"] = "needs_review"
            row["note"] = "تعذر تأكيد المواعيد بتاريخ اليوم؛ راجع موقع المسجد الرسمي."
        # Safe, short diagnostic to help the site owner identify the real issue.
        # Visible only when examining data/mosques.json or the workflow logs.
        row["diagnostic"] = f"{type(exc).__name__}: {original_failure.replace(chr(10), ' ')[:180]}"
    if mosque["id"] in INDEPENDENT_SOURCES and row["status"] not in ("updated", "partial"):
        return _independent_or_manual(row, mosque, target)
    return _manual_or_row(row, mosque, target)



def _huda_pdf_fallback(mosque: dict, target: date) -> dict:
    """Use an offline PDF row ONLY when independently verified for this date.

    The supplied annual PDF has NO printed year and 2026 DST inconsistencies.
    Never apply its month/day records to a new year automatically.
    """
    row = _initial_record(mosque)
    row["checked_at"] = datetime.now(TZ).isoformat(timespec="seconds")
    filename = ROOT / "al_huda_annual.json"
    data = json.loads(filename.read_text(encoding="utf-8"))
    verified = data.get("verified_dates", {}).get(target.isoformat())
    if not verified:
        raise ValueError("Al-Huda annual PDF does not state a year; today's date is not independently verified")
    key = target.strftime("%d-%b")
    day = data["rows"][key]
    values = {"adhan": day["adhan"], "iqamah": day["iqamah"]}
    digest = hashlib.sha256(json.dumps(values, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    if digest != verified["row_sha256"]:
        raise ValueError("Al-Huda annual timetable row changed since date-specific verification")
    validate_times(day["adhan"], day["iqamah"])
    row["adhan"] = copy.deepcopy(day["adhan"])
    row["iqamah"] = copy.deepcopy(day["iqamah"])
    row["status"] = "updated"
    row["source_date"] = target.isoformat()
    row["updated_at"] = row["checked_at"]
    row["timetable_url"] = data["source_url"]
    row["source_type"] = "pdf_local_verified_date"
    row["note"] = "These daily times match the mosque's dated official website. The saved annual PDF is used because the live request returned HTTP 403."
    return row


def _read_manual_confirmed(mosque: dict, target: date) -> dict | None:
    """Read administrator-checked date-specific Jamaat rows from the repo.

    This is NOT a feed and never infers dates, shifts BST/GMT or reuses the
    last recorded day. Only a row for the precise Europe/London date can pass.
    """
    filename = ROOT / "verified_mosque_times.json"
    if not filename.is_file():
        return None  # Compatible with older deployments without this file.
    data = json.loads(filename.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError("Unsupported verified timetable schema")
    entry = data.get("mosques", {}).get(mosque["id"], {}).get("dates", {}).get(target.isoformat())
    if entry is None:
        return None
    if not isinstance(entry, dict):
        raise ValueError("Manual daily record must be an object")
    confirmation = entry.get("confirmation_type")
    if confirmation not in ("dated_mosque_timetable", "confirmed_with_mosque"):
        raise ValueError("Manual row must declare how the mosque timetable was checked")
    if len(str(entry.get("evidence", "")).strip()) < 10:
        raise ValueError("Manual row needs a clear provenance note")
    if len(str(entry.get("checked_by", "")).strip()) < 3:
        raise ValueError("Manual row needs a checker attribution")
    try:
        checked_on = date.fromisoformat(str(entry["checked_on"]))
    except (KeyError, ValueError) as exc:
        raise ValueError("Manual row needs checked_on in YYYY-MM-DD format") from exc
    if not (0 <= (target - checked_on).days <= 366):
        raise ValueError("Manual timetable confirmation date is outside allowed period")
    adhan = {p: entry.get("adhan", {}).get(p) for p in PRAYERS}
    iqamah = {p: entry.get("iqamah", {}).get(p) for p in PRAYERS}
    if not any(iqamah.values()):
        raise ValueError("Manual row contains no Jamaat times")
    # A real mosque may provide Jamaat-only timings without adhan begins.
    # They are still useful and must not be replaced by calculated times.
    for prayer in PRAYERS:
        begins, congregation = adhan[prayer], iqamah[prayer]
        if begins is not None and (not isinstance(begins, str) or _clock(begins) != begins):
            raise ValueError(f"Invalid manual prayer start for {prayer}")
        if congregation is not None and (not isinstance(congregation, str) or _clock(congregation) != congregation):
            raise ValueError(f"Invalid manual Jamaat time for {prayer}")
        if begins and congregation and _minutes(congregation) < _minutes(begins):
            raise ValueError(f"Manual Jamaat before prayer start for {prayer}")
    for series in (adhan, iqamah):
        times = [series[p] for p in PRAYERS if series[p]]
        if any(_minutes(b) <= _minutes(a) for a, b in zip(times, times[1:])):
            raise ValueError("Manual timetable is not in chronological order")
    source_url = entry.get("source_url") or mosque["timetable_url"]
    url_parts = urlsplit(source_url)
    if url_parts.scheme != "https" or not url_parts.hostname or url_parts.username:
        raise ValueError("Manual timetable source must be an HTTPS web address")
    row = _initial_record(mosque)
    row.update(
        adhan=adhan, iqamah=iqamah,
        status="manual_dated" if all(iqamah.values()) else "manual_partial",
        source_date=target.isoformat(),
        source_type="administrator_checked_daily",
        timetable_url=source_url,
        checked_at=datetime.now(TZ).isoformat(timespec="seconds"),
        updated_at=checked_on.isoformat(),
        note="هذه مواعيد أدخلها مسؤول البوابة من جدول مؤرخ أو تأكيد مباشر؛ تأكد من المسجد عند حدوث تغييرات.",
        confirmation_type=confirmation,
        evidence=entry["evidence"].strip(),
    )
    return row


def _manual_or_row(row: dict, mosque: dict, target: date) -> dict:
    if row.get("status") in ("updated", "partial"):
        return row  # Never supersede a working dated official source.
    try:
        manually_checked = _read_manual_confirmed(mosque, target)
        return manually_checked if manually_checked is not None else row
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        LOG.warning("Invalid manually entered timetable for %s: %s", mosque["id"], exc)
        row["diagnostic"] = f"Manual row rejected: {type(exc).__name__}: {str(exc)[:150]}"
        return row


# A same-date, time-limited safety net for temporary connection errors.
# It can NEVER create a timetable for a source that has never succeeded, or
# reuse the previous day's timetable. Keep original checked_at: the next build
# cannot silently extend its validity.
PREVIOUS_PUBLIC_URL = "https://ahmeeed-abdu.github.io/sheffield-masjid-times/data/mosques.json"
MAX_RECOVERY_AGE = timedelta(hours=4)
RECOVERABLE_STATUSES = {"updated", "partial", "third_party_dated", "third_party_partial"}


def _previous_public_payload() -> dict | None:
    try:
        response = requests.get(
            PREVIOUS_PUBLIC_URL,
            timeout=(3, 7),
            headers={"Accept": "application/json", "Cache-Control": "no-cache",
                     "User-Agent": "SheffieldMasjidTimes/1.0 (same-day recovery)"},
            allow_redirects=False,
        )
        if response.status_code != 200 or len(response.content) > 2_000_000:
            return None
        if "json" not in response.headers.get("Content-Type", "application/json").lower():
            return None
        result = response.json()
        return result if isinstance(result, dict) else None
    except (requests.RequestException, ValueError, json.JSONDecodeError):
        return None


def _recover_same_day(rows: list[dict], snapshot: dict | None, target: date,
                      now: datetime) -> list[dict]:
    """Reuse a *verified earlier today* row for up to four hours, once.

    This handles transient source outages (HTTP 403, timeout, SSL errors) but
    never fills a permanently unconnected mosque or invents prayer times.
    """
    if not isinstance(snapshot, dict) or snapshot.get("date") != target.isoformat():
        return rows
    if snapshot.get("timezone") != "Europe/London" or snapshot.get("demo") is True:
        return rows
    previous_rows = snapshot.get("mosques")
    if not isinstance(previous_rows, list) or len(previous_rows) > 100:
        return rows
    by_id = {x.get("id"): x for x in previous_rows if isinstance(x, dict)}
    existing = {m["id"]: m for m in MOSQUES}
    recovered = []
    for current in rows:
        if current.get("status") in RECOVERABLE_STATUSES or current.get("status") in (
                "manual_dated", "manual_partial"):
            recovered.append(current)
            continue
        old = by_id.get(current.get("id"))
        mosque = existing.get(current.get("id"))
        if (not old or not mosque or old.get("name_en") != mosque["name_en"]
                or old.get("source_date") != target.isoformat()
                or old.get("status") not in RECOVERABLE_STATUSES):
            recovered.append(current)
            continue
        try:
            stamp = datetime.fromisoformat(str(old["checked_at"]))
            if stamp.tzinfo is None:
                raise ValueError("Missing offset in source timestamp")
            age = now - stamp.astimezone(TZ)
            if not timedelta(0) <= age <= MAX_RECOVERY_AGE:
                raise ValueError("Previously verified row is too old")
            adhan, iqamah = old["adhan"], old["iqamah"]
            if not isinstance(adhan, dict) or not isinstance(iqamah, dict):
                raise ValueError("Bad snapshot time mapping")
            validate_independent_times(adhan, iqamah)
        except (KeyError, ValueError, TypeError):
            recovered.append(current)
            continue
        row = copy.deepcopy(old)
        row["status"] = ("cached_third_party_today" if old["status"].startswith("third_party")
                         else "cached_official_today")
        row["note"] = ("آخر مواقيت مؤرخة جرى فحصها اليوم. تعذّر تحديث المصدر الآن؛ "
                       "تحقق من المسجد قبل الاعتماد عليها. لا تُستخدم بعد أربع ساعات من آخر فحص ناجح.")
        if old["status"].startswith("third_party"):
            row["note"] += " المصدر دليل مستقل وليس تأكيدًا من إدارة المسجد."
        row["last_attempt_at"] = current.get("checked_at") or now.isoformat(timespec="seconds")
        if current.get("diagnostic"):
            row["diagnostic"] = current["diagnostic"]
        # checked_at/updated_at remain from the ORIGINAL successful fetch.
        recovered.append(row)
    return recovered


_cache_lock = Lock()
_cache_data: dict | None = None
_cache_until: datetime | None = None


def build_payload() -> dict:
    now = datetime.now(TZ)
    day = now.date()
    previous = _previous_public_payload()
    with ThreadPoolExecutor(max_workers=3) as pool:
        rows = list(pool.map(lambda m: _read_official(m, day), MOSQUES))
    rows = _recover_same_day(rows, previous, day, datetime.now(TZ))
    return {
        "date": day.isoformat(),
        "timezone": "Europe/London",
        "generated_at": datetime.now(TZ).isoformat(timespec="minutes"),
        "demo": False,
        "cache_seconds": CACHE_SECONDS,
        "mosques": rows,
        "disclaimer": "مواعيد منشورة على مواقع المساجد؛ التحقق الآلي لا يعني موافقة إدارات المساجد. لا يتم التخمين.",
    }


app = FastAPI(title="Sheffield Masjid Times Portal", version="0.2.0")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/health")
def health():
    return {"ok": True, "london_now": datetime.now(TZ).isoformat(timespec="seconds")}


@app.get("/api/mosques")
def mosques():
    global _cache_data, _cache_until
    now = datetime.now(TZ)
    with _cache_lock:
        if _cache_data is None or _cache_until is None or now >= _cache_until or _cache_data["date"] != now.date().isoformat():
            _cache_data = build_payload()
            _cache_until = now + timedelta(seconds=CACHE_SECONDS)
        return copy.deepcopy(_cache_data)
