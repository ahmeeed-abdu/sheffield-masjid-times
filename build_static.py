"""Produce the complete, hostable GitHub Pages artifact for the portal.

No web server, database, paid plan or deployment secret is required.
If source collection fails the produced JSON contains no unverified times.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from shutil import copy2, rmtree
from zoneinfo import ZoneInfo

# Allow invocation as `python scripts/build_static.py` from any working directory.
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import MOSQUES, _initial_record, build_payload  # noqa: E402

TZ = ZoneInfo('Europe/London')


def empty_payload() -> dict:
    """Safe offline layout smoke test; never ship fabricated prayer times."""
    now = datetime.now(TZ)
    rows = [_initial_record(m) for m in MOSQUES]
    for row in rows:
        row['note'] = 'مواعيد هذا المسجد لم تُفحص في وضع المعاينة؛ راجع موقعه الرسمي.'
    return {
        'date': now.date().isoformat(),
        'timezone': 'Europe/London',
        'generated_at': now.isoformat(timespec='seconds'),
        'demo': False,
        'mosques': rows,
        'disclaimer': 'معاينة بدون اتصال بالمصادر؛ لا تتوفر مواعيد صلاة مؤكدة.',
    }


def prepare_site(destination: Path, *, online: bool = True) -> dict:
    # Build output can be arbitrarily named; never delete the source tree.
    destination = destination.resolve()
    inside_project = ROOT in destination.parents
    # Only public/ may be rebuilt inside the repository; do not risk deleting
    # src/, tests/, .github/, or the parent directory via a typo in --output.
    if (destination == ROOT or destination in ROOT.parents or
            (inside_project and destination.relative_to(ROOT).parts[0] != 'public')):
        raise ValueError('Destination would overwrite project/source files')
    if destination.exists():
        rmtree(destination)
    (destination / 'assets').mkdir(parents=True)
    (destination / 'data').mkdir()
    copy2(ROOT / 'static' / 'index.html', destination / 'index.html')
    copy2(ROOT / 'static' / 'styles.css', destination / 'assets' / 'styles.css')
    copy2(ROOT / 'static' / 'app.js', destination / 'assets' / 'app.js')
    (destination / '.nojekyll').write_text('', encoding='utf-8')

    payload = build_payload() if online else empty_payload()
    (destination / 'data' / 'mosques.json').write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + '\n',
        encoding='utf-8',
    )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description='Create a zero-cost GitHub Pages website')
    parser.add_argument('--output', type=Path, default=ROOT / 'public')
    parser.add_argument('--offline', action='store_true', help='Generate placeholders only; NEVER fake live times')
    args = parser.parse_args()
    payload = prepare_site(args.output, online=not args.offline)
    counts = {}
    for row in payload['mosques']:
        counts[row['status']] = counts.get(row['status'], 0) + 1
    print(f"Built {args.output}: {len(payload['mosques'])} mosques, {counts}, date {payload['date']}")


if __name__ == '__main__':
    main()
