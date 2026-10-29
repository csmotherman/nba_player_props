"""Run the real-data audit on the local warehouse and write data/discovery/leakage_audit.json.
    python scripts/run_leakage_audit.py [seasons comma list]"""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent; sys.path.insert(0, str(ROOT))
from nba_props.storage.db import connect
from nba_props.validation import audit
seasons = (sys.argv[1] if len(sys.argv) > 1 else '2024-25,2025-26,2026-27').split(',')
con = connect(read_only=True)
res = audit.run_all(con, seasons)
(ROOT / 'data' / 'discovery' / 'leakage_audit.json').write_text(json.dumps(res, indent=1, sort_keys=True, default=str) + '\n')
tt = res['time_travel']
print('scan', {s: {k: v for k, v in d.items() if 'violation' in k or k in ('rows', 'duplicate_keys')} for s, d in res['scan'].items()})
print('independent', res['independent']); print('time-travel runs', len(tt), 'with mismatches:', sum(1 for t in tt if t['mismatching_columns']))
print('poison', [(p['season'], p['rows'], p['mismatching_columns']) for p in res['poison']]); print('unknown tip', res['unknown_tip']); print('roster', res['roster'])
