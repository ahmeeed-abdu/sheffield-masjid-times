"""Validate the GitHub Pages artifact without network access."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.build_static import prepare_site
from app import MOSQUES


class StaticBuildTests(unittest.TestCase):
    def test_offline_build_has_eight_mosques_and_zero_invented_times(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / 'the-project-subpath'
            payload = prepare_site(dest, online=False)
            self.assertEqual(len(payload['mosques']), len(MOSQUES))
            self.assertTrue((dest / 'index.html').is_file())
            self.assertTrue((dest / 'assets' / 'app.js').is_file())
            self.assertTrue((dest / 'assets' / 'styles.css').is_file())
            self.assertTrue((dest / '.nojekyll').is_file())
            data = json.loads((dest / 'data' / 'mosques.json').read_text())
            self.assertFalse(data['demo'])
            self.assertTrue(all(all(not val for val in row['iqamah'].values()) for row in data['mosques']))
            html = (dest / 'index.html').read_text()
            js = (dest / 'assets' / 'app.js').read_text()
            self.assertIn('./assets/app.js', html)
            self.assertIn('./assets/styles.css', html)
            self.assertNotIn('/api/mosques', js)
            self.assertIn('data/mosques.json', js)
            self.assertNotIn('DEMO_MOSQUES', js)

    def test_online_build_uses_generated_payload_and_never_injects_demo(self):
        from scripts import build_static
        from datetime import date
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            fake = build_static.empty_payload()
            fake['mosques'][0]['status'] = 'updated'
            fake['mosques'][0]['source_date'] = date.today().isoformat()  # builder copies payload unchanged
            fake['mosques'][0]['iqamah']['fajr'] = '05:30'
            with patch('scripts.build_static.build_payload', return_value=fake) as build:
                written = build_static.prepare_site(Path(tmp) / 'site', online=True)
            build.assert_called_once()
            self.assertEqual(written, fake)
            data = json.loads((Path(tmp) / 'site' / 'data' / 'mosques.json').read_text())
            self.assertEqual(data['mosques'][0]['iqamah']['fajr'], '05:30')


if __name__ == '__main__':
    unittest.main()
