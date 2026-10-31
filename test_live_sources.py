"""Source-specific and safety regression tests using official-site-shaped fixtures.

Network fetches are mocked because this environment has no outbound DNS access.
"""
from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from app import MOSQUES, _read_official, app, parse_mwh_home, parse_industry, validate_times


MWHS_DAILY = '''
<html><head><title>Muslim Welfare House Sheffield</title></head><body>
<h2>Sheffield Prayer Times — Muslim Welfare House Sheffield</h2>
<div>Sat 31 October 2026</div>
<h2>Prayer Times for Sat 31 October 2026</h2>
<div>fajr <b>05:10</b><span>Iqamah 05:45</span></div>
<div>sunrise <b>07:00</b><span>--:--</span></div>
<div>dhuhr <b>11:50</b><span>Iqamah 13:10</span></div>
<div>asr <b>14:07</b><span>Iqamah 14:30</span></div>
<div>maghrib <b>16:39</b><span>Iqamah 16:39</span></div>
<div>isha <b>18:29</b><span>Iqamah 19:30</span></div>
<div>Jummah Prayer 12:45</div>
<h2>Upcoming Events</h2><p>Fajr class at 05:45</p>
</body></html>'''

HUDA_DAILY = '''<h2>Today’s prayer times</h2><p>Saturday, 31/10/2026</p>
<p>Fajr 5:18 AM Jamāʿah · 5:30 AM</p>
<p>Ẓuhr 11:51 AM Jamāʿah · 12:30 PM</p>
<p>ʿAṣr 2:08 PM Jamāʿah · 2:45 PM</p>
<p>Maghrib 4:38 PM Jamāʿah · 4:38 PM</p>
<p>ʿIshāʾ 6:15 PM Jamāʿah · 6:45 PM</p>'''

SUNNAH_DAILY = '''<h2>Prayer Times</h2>
<div>Fajr Begins: 5:44 am Jamaat: 6:00 am</div>
<div>Dhuhur Begins: 11:51 am Jamaat: 12:30 pm</div>
<div>Asr Begins: 2:07 pm Jamaat: 2:30 pm</div>
<div>Maghrib Begins: 4:37 pm Jamaat: 4:37 pm</div>
<div>Isha Begins: 5:55 pm Jamaat: 7:15 pm</div>
<a>View Full Timetable</a>'''


def fake_response(html: str, status=200, media='text/html; charset=utf-8'):
    return Mock(status_code=status, content=html.encode(), text=html, headers={'Content-Type':media})


class DailyParserTests(unittest.TestCase):
    day = date(2026, 10, 31)

    def test_mwh_daily_31st(self):
        adhan, iqamah = parse_mwh_home(MWHS_DAILY, self.day)
        self.assertEqual(adhan['maghrib'], '16:39')
        self.assertEqual(iqamah['isha'], '19:30')
        self.assertEqual(iqamah['fajr'], '05:45')
        validate_times(adhan, iqamah)

    def test_mwh_stale_date_does_not_display(self):
        with self.assertRaisesRegex(ValueError, 'date differs'):
            parse_mwh_home(MWHS_DAILY, date(2026, 11, 1))

    def test_mwh_bad_day_of_week_does_not_display(self):
        with self.assertRaisesRegex(ValueError, 'date differs'):
            parse_mwh_home(MWHS_DAILY.replace('Sat 31 October 2026', 'Fri 31 October 2026'), self.day)

    def test_mwh_summer_combined_prayer_is_partial_not_guessed(self):
        summer = MWHS_DAILY.replace('Iqamah 19:30', 'Iqamah After Maghrib')
        adhan, iqamah = parse_mwh_home(summer, self.day)
        self.assertEqual(iqamah['maghrib'], '16:39')
        self.assertIsNone(iqamah['isha'])
        validate_times(adhan, iqamah)
        mosque = next(m for m in MOSQUES if m['id']=='mwh')
        with patch('app.requests.get', return_value=fake_response(summer)):
            row = _read_official(mosque, self.day)
        self.assertEqual(row['status'], 'partial')
        self.assertEqual(row['source_date'], '2026-10-31')
        self.assertIn('بعد المغرب', row['note'])

    def test_mwh_missing_iqamah(self):
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            parse_mwh_home(MWHS_DAILY.replace('Iqamah 19:30', 'Not currently published'), self.day)

    def test_mwh_ignores_event_times(self):
        adhan, _ = parse_mwh_home(MWHS_DAILY.replace('Upcoming Events', 'Upcoming Events Fajr 03:00 Iqamah 03:15'), self.day)
        self.assertEqual(adhan['fajr'], '05:10')

    def test_error_when_iqamah_before_start(self):
        adhan, iqamah = parse_mwh_home(MWHS_DAILY.replace('Iqamah 05:45', 'Iqamah 04:45'), self.day)
        with self.assertRaisesRegex(ValueError, 'before prayer begins'):
            validate_times(adhan, iqamah)

    def test_three_sources_are_connected(self):
        connected = {row['id'] for row in MOSQUES if row.get('parser')}
        self.assertEqual(connected, {'huda', 'sunnah', 'mwh', 'industry'})

    def test_industry_dated_parser(self):
        fixture = """<h2>Today's Prayer Times</h2><h3>31st October 2026 20 Rabi</h3>
        <p>Full Timetable</p><h4>Begins 'Iqamah</h4>
        <p>Fajr 5:18 am 6:00 am</p><p>Dhuhr 11:51 am 1:30 pm</p>
        <p>Asr 2:08 pm 2:45 pm</p><p>Maghrib 4:38 pm 4:38 pm</p>
        <p>Isha 6:15 pm 7:00 pm</p><footer>Site navigation</footer>"""
        adhan, iqamah = parse_industry(fixture, self.day)
        validate_times(adhan, iqamah)
        self.assertEqual(iqamah['dhuhr'], '13:30')
        mosque = next(m for m in MOSQUES if m['id']=='industry')
        with patch('app.requests.get', return_value=fake_response(fixture)):
            row = _read_official(mosque, self.day)
        self.assertEqual(row['status'], 'updated')
        self.assertEqual(row['source_date'], '2026-10-31')
        with self.assertRaisesRegex(ValueError, 'date differs'):
            parse_industry(fixture, date(2026, 11, 1))

    def test_industry_invalid_asr_does_not_publish(self):
        fixture = """<h2>Today's Prayer Times</h2><h3>31st October 2026</h3>
        <p>Begins Iqamah Fajr 5:18 am 6:00 am Dhuhr 11:51 am 1:30 pm
        Asr 12:00 am 2:45 pm Maghrib 4:38 pm 4:38 pm Isha 6:15 pm 7:00 pm</p>"""
        mosque = next(m for m in MOSQUES if m['id']=='industry')
        with patch('app.requests.get', return_value=fake_response(fixture)):
            row = _read_official(mosque, self.day)
        self.assertEqual(row['status'], 'needs_review')
        self.assertTrue(all(not v for v in row['iqamah'].values()))

    def test_mwh_reads_home_page_not_monthly(self):
        mosque = next(m for m in MOSQUES if m['id']=='mwh')
        self.assertEqual(mosque['timetable_url'], 'https://www.mwhs.org.uk/')

    def test_dated_mwh_row(self):
        mosque = next(m for m in MOSQUES if m['id']=='mwh')
        with patch('app.requests.get', return_value=fake_response(MWHS_DAILY)) as mock_get:
            row = _read_official(mosque, self.day)
        self.assertEqual(row['status'], 'updated')
        self.assertEqual(row['source_date'], '2026-10-31')
        self.assertEqual(row['iqamah']['maghrib'], '16:39')
        self.assertTrue(row['checked_at'])
        self.assertFalse(mock_get.call_args.kwargs['allow_redirects'])

    def test_dated_huda_row(self):
        mosque = next(m for m in MOSQUES if m['id']=='huda')
        with patch('app.requests.get', return_value=fake_response(HUDA_DAILY)):
            row = _read_official(mosque, self.day)
        self.assertEqual(row['status'], 'updated')
        self.assertEqual(row['iqamah']['isha'], '18:45')

    def test_undated_sunnah_row_not_marked_confirmed(self):
        mosque = next(m for m in MOSQUES if m['id']=='sunnah')
        with patch('app.requests.get', return_value=fake_response(SUNNAH_DAILY)):
            row = _read_official(mosque, self.day)
        self.assertEqual(row['status'], 'undated')
        self.assertIsNone(row['source_date'])
        self.assertEqual(row['iqamah']['fajr'], '06:00')

    def test_stale_dated_source_hidden(self):
        mosque = next(m for m in MOSQUES if m['id']=='mwh')
        with patch('app.requests.get', return_value=fake_response(MWHS_DAILY)):
            row = _read_official(mosque, date(2026, 11, 1))
        self.assertEqual(row['status'], 'needs_review')
        self.assertTrue(all(val is None for val in row['iqamah'].values()))

    def test_redirect_is_not_followed(self):
        mosque = next(m for m in MOSQUES if m['id']=='huda')
        with patch('app.requests.get', return_value=fake_response('', status=302)):
            row = _read_official(mosque, self.day)
        self.assertEqual(row['status'], 'needs_review')
        self.assertTrue(all(val is None for val in row['iqamah'].values()))

    def test_non_html_is_rejected(self):
        mosque = next(m for m in MOSQUES if m['id']=='huda')
        with patch('app.requests.get', return_value=fake_response('%PDF-1.0', media='application/pdf')):
            row = _read_official(mosque, self.day)
        self.assertEqual(row['status'], 'needs_review')

    def test_api_health_and_page(self):
        client = TestClient(app)
        self.assertTrue(client.get('/api/health').json()['ok'])
        self.assertEqual(client.get('/').status_code, 200)
        self.assertIn('مواقيت',client.get('/').text)
        self.assertEqual(client.get('/static/app.js').status_code, 200)


if __name__ == '__main__':
    unittest.main()
