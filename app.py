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
MOSQUES = [
    dict(id="huda", name_ar="مسجد الهدى", name_en="Al-Huda Islamic Centre", area="Broomhall", address="Hanover St, Sheffield S3 7WT", website="https://masjidhudasheff.com/", timetable_url="https://masjidhudasheff.com/", source_type="html", parser="huda"),
    dict(id="sunnah", name_ar="مسجد السنة", name_en="Masjid Sunnah Sheffield", area="Pitsmoor", address="18 Kirk St, Sheffield S4 7JX", website="https://masjidsunnahsheffield.co.uk/", timetable_url="https://masjidsunnahsheffield.co.uk/", source_type="html", parser="sunnah"),
    dict(id="mwh", name_ar="مسجد بيت الرعاية الإسلامية", name_en="Muslim Welfare House", area="Broomhall", address="10-12 Severn Rd, Sheffield S10 2SU", website="https://www.mwhs.org.uk/", timetable_url="https://www.mwhs.org.uk/", source_type="html", parser="mwh_home"),
    dict(id="baitul", name_ar="مسجد بيت المكرم", name_en="Baitul Mukarram Jame Masjid", area="Highfield", address="358 London Rd, Sheffield S2 4NB", website="https://www.baitulmukarramjamemasjid.com/", timetable_url="https://www.baitulmukarramjamemasjid.com/", source_type="dynamic", parser=None),
    dict(id="umar", name_ar="مسجد عمر", name_en="Masjid Umar (YMA)", area="Pitsmoor", address="306 Barnsley Rd, Sheffield S4 7AH", website="https://www.ymasheffield.org/", timetable_url="https://www.ymasheffield.org/prayer-timetable", source_type="pdf", parser=None),
    dict(id="madina", name_ar="مسجد المدينة", name_en="Madina Masjid Sheffield", area="Lowfield", address="24 Wolseley Rd, Sheffield S8 0ZU", website="https://www.madinamasjid.org.uk/", timetable_url="https://mawaqit.net/en/madina-masjid-sheffield-sheffield-s8-0zu-united-kingdom", source_type="dynamic", parser=None),
    dict(id="grand", name_ar="مسجد شيفلد الكبير", name_en="Sheffield Grand Mosque", area="Grimesthorpe", address="Grimesthorpe Rd, Sheffield S4 8DE", website="https://emaantrust.mosqueprayertimes.org/prayer-times", timetable_url="https://emaantrust.mosqueprayertimes.org/prayer-times", source_type="dynamic", parser=None),
    dict(id="industry", name_ar="مسجد الجامع المركزي", name_en="Markazi Jamia Mosque", area="Darnall", address="13 Industry Rd, Sheffield S9 5FP", website="https://www.industryroadmosque.com/", timetable_url="https://www.industryroadmosque.com/prayer-times/", source_type="html", parser="industry"),
]


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


def _read_official(mosque: dict, target: date) -> dict:
    row = _initial_record(mosque)
    if not mosque["parser"]:
        row["note"] = "هذا المصدر غير مربوط آليًا بعد؛ تحقق من موقع المسجد الرسمي."
        return row
    row["checked_at"] = datetime.now(TZ).isoformat(timespec="seconds")
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
        row["updated_at"] = row["checked_at"]  # Compatibility with older UI.
    except (requests.RequestException, ValueError, RuntimeError, KeyError) as exc:
        if mosque["id"] == "huda" and "HTTP 403" in str(exc):
            try:
                return _huda_pdf_fallback(mosque, target)
            except (ValueError, KeyError, OSError, json.JSONDecodeError) as fallback_exc:
                # The downloaded PDF has no year. A missing verified date is
                # a normal safe failure, not permission to guess a schedule.
                LOG.warning("Al-Huda PDF not confirmed: %s", fallback_exc)
                original_failure = f"HTTP 403; PDF fallback unavailable: {fallback_exc}"
            else:
                original_failure = str(exc)
        else:
            original_failure = str(exc)
        LOG.warning("Unable to verify source %s: %s", mosque["id"], original_failure)
        row["status"] = "needs_review"
        row["note"] = "تعذر تأكيد المواعيد بتاريخ اليوم؛ راجع موقع المسجد الرسمي."
        # Safe, short diagnostic to help the site owner identify the real issue.
        # Visible only when examining data/mosques.json or the workflow logs.
        row["diagnostic"] = f"{type(exc).__name__}: {original_failure.replace(chr(10), ' ')[:180]}"
    return row



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


_cache_lock = Lock()
_cache_data: dict | None = None
_cache_until: datetime | None = None


def build_payload() -> dict:
    day = datetime.now(TZ).date()
    with ThreadPoolExecutor(max_workers=3) as pool:
        rows = list(pool.map(lambda m: _read_official(m, day), MOSQUES))
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
