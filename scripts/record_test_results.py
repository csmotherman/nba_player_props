"""Run the offline suite and record the outcome in data/discovery/test_results.json (read by the report). Deterministic content except counts."""
import json, subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
extra = sys.argv[1:]
p = subprocess.run([sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider', '--tb=short', '-rA'] + extra, capture_output=True, text=True, cwd=ROOT)
lines = p.stdout.splitlines()
res = [l for l in lines if l.startswith(('PASSED ', 'FAILED ', 'ERROR ', 'SKIPPED ')) and 'tests/' in l]
import re
summary = next((l for l in reversed(lines) if re.match(r'^\d+ (passed|failed|skipped|error).* in [\d.]+s', l)), '')
by_file = {}
for l in res:
    status, rest = l.split(' ', 1)
    f = rest.split('::')[0]
    if not f.startswith('tests/'):
        continue
    by_file.setdefault(f, {'PASSED': 0, 'FAILED': 0, 'ERROR': 0, 'SKIPPED': 0})[status] += 1
(ROOT / 'data' / 'discovery' / 'test_results.json').write_text(json.dumps(dict(command='pytest ' + ' '.join(extra), summary=summary, returncode=p.returncode, by_file=by_file), indent=1, sort_keys=True) + '\n')
print(summary); print(json.dumps(by_file, indent=1))
sys.exit(p.returncode)
