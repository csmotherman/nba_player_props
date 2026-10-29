"""Run identity checks + player/team reconciliation on the REAL warehouse and write data/discovery/formula_checks.json.

    python scripts/run_formula_checks.py [db_path]
Deterministic output (no timestamps) so regenerating unchanged data does not change the file.
"""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent; sys.path.insert(0, str(ROOT))
from nba_props.storage.db import connect
from nba_props.validation import formulas

con = connect(sys.argv[1] if len(sys.argv) > 1 else None, read_only=True)
def rnd(o):
    if isinstance(o, float): return round(o, 6)
    if isinstance(o, dict): return {k: rnd(v) for k, v in o.items()}
    if isinstance(o, list): return [rnd(v) for v in o]
    return o
out = dict(identities=rnd(formulas.run(con)), player_vs_team=rnd(formulas.reconcile_player_vs_team(con)),
           rows=dict(player_game=con.execute("SELECT count(*) FROM player_game WHERE season IN ('2023-24','2024-25','2025-26')").fetchone()[0]))
(ROOT / 'data' / 'discovery' / 'formula_checks.json').write_text(json.dumps(out, indent=1, sort_keys=True) + '\n')
print({k: (v['verdict'], v['n']) for k, v in out['identities'].items()})
