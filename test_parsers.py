import unittest
from datetime import date
from unittest.mock import patch, Mock

from app import parse_huda, parse_sunnah, parse_mwh, last_sunday, _read_official, MOSQUES


class ParserTests(unittest.TestCase):
    def test_huda(self):
        html = '''<main><h2>Today’s prayer times</h2><div>Saturday, 31/10/2026</div>
        <div>Fajr <b>5:18 AM</b> Jamāʿah · <b>5:30 AM</b></div>
        <div>Sunrise 7:01 AM</div>
        <div>Ẓuhr <b>11:51 AM</b> Jamāʿah · <b>12:30 PM</b></div>
        <div>ʿAṣr <b>2:08 PM</b> Jamāʿah · <b>2:45 PM</b></div>
        <div>Maghrib <b>4:38 PM</b> Jamāʿah · <b>4:38 PM</b></div>
        <div>ʿIshāʾ <b>6:15 PM</b> Jamāʿah · <b>6:45 PM</b></div>
        </main>'''
        a, i = parse_huda(html, date(2026, 10, 31))
        self.assertEqual(a['fajr'], '05:18')
        self.assertEqual(i['isha'], '18:45')
        self.assertEqual(i['asr'], '14:45')
        with self.assertRaises(ValueError):
            parse_huda(html, date(2026, 11, 1))

    def test_sunnah(self):
        html = '''<h2>Prayer Times</h2>
        <p>Fajr Begins: 5:44 am Jamaat: 6:00 am</p>
        <p>Dhuhur Begins: 11:51 am Jamaat: 12:30 pm</p>
        <p>Asr Begins: 2:07 pm Jamaat: 2:30 pm</p>
        <p>Maghrib Begins: 4:37 pm Jamaat: 4:37 pm</p>
        <p>Isha Begins: 5:55 pm Jamaat: 7:15 pm</p>
        <a>View Full Timetable</a>'''
        a, i = parse_sunnah(html, date(2026, 10, 31))
        self.assertEqual(a['dhuhr'], '11:51')
        self.assertEqual(i['isha'], '19:15')
        self.assertEqual(i['fajr'], '06:00')

    def _mwh_fixture(self, dst_correct):
        days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
        rows = []
        for n in range(1, 32):
            week = date(2026, 10, n).weekday()
            mag = '17:53' if n == 24 else ('16:51' if dst_correct else '17:51') if n == 25 else '17:39'
            rows.append(f'<tr><td>{n} {days[week]}</td><td>06:10</td><td>12:50</td><td>15:07</td><td>{mag}</td><td>19:29</td></tr>')
        html = '<h2>October 2026</h2><table>'+''.join(rows)+'</table>'
        html += '<h3>Iqama Times</h3><div>Dates 21-31 Fajr 6:45 Dhuhr 13:30 Asr 15:30 Isha 20:15</div><h3>Jummah Prayer</h3>'
        return html

    def test_mwh_rejects_missing_dst_rollback(self):
        with self.assertRaisesRegex(ValueError, 'BST to GMT'):
            parse_mwh(self._mwh_fixture(False), date(2026, 10, 31))

    def test_mwh_accepts_dst_corrected(self):
        a, i = parse_mwh(self._mwh_fixture(True), date(2026, 10, 31))
        self.assertEqual(a['fajr'], '06:10')
        self.assertEqual(i['dhuhr'], '13:30')
        self.assertIsNone(i['maghrib'])

    def test_last_sunday(self):
        self.assertEqual(last_sunday(2026, 10), date(2026, 10, 25))
        self.assertEqual(last_sunday(2026, 3), date(2026, 3, 29))

    def test_fail_closed_when_source_unavailable(self):
        with patch('app.requests.get', side_effect=__import__('requests').ConnectionError('no network')):
            row = _read_official(MOSQUES[0], date(2026,10,31))
        self.assertEqual(row['status'], 'needs_review')
        self.assertTrue(all(v is None for v in row['iqamah'].values()))

if __name__ == '__main__':
    unittest.main()
