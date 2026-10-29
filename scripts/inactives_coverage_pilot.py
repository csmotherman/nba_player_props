"""Does BoxScoreSummaryV3.InactivePlayers cover older games? Samples games evenly across each season, fetches the summary (resumable,
raw-store backed) and records per-game inactive counts. Writes data/discovery/inactives_coverage.json.
    python scripts/inactives_coverage_pilot.py [games_per_season=12]"""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent; sys.path.insert(0, str(ROOT))
from nba_props.storage.db import connect
from nba_props.ingestion.runner import Ingestor
from nba_props.ingestion import normalize as N, derive
from nba_props.storage.db import upsert

n = int(sys.argv[1]) if len(sys.argv) > 1 else 12
con = connect(); ing = Ingestor(con, command='inactives-pilot')
out = {}
for season in ('2023-24', '2024-25', '2025-26'):
    games = [r[0] for r in con.execute("SELECT game_id FROM games WHERE season=? AND season_type='regular' AND in_gamelog ORDER BY game_date, game_id", [season]).fetchall()]
    sample = [games[int(i * (len(games) - 1) / (n - 1))] for i in range(n)]
    rows = []
    for gid in sample:
        fr, at = ing.get('BoxScoreSummaryV3', {'game_id': gid}, season)
        if fr is None:
            rows.append(dict(game_id=gid, ok=False)); continue
        df = fr['InactivePlayers']
        if len(df):
            upsert(con, 'historical_inactives', N.inactives(df, at))
        d = con.execute("SELECT game_date FROM games WHERE game_id=?", [gid]).fetchall()[0][0]
        rows.append(dict(game_id=gid, game_date=str(d), ok=True, inactives=int(len(df)), teams_with_inactives=int(df.teamId.nunique()) if len(df) else 0))
    ok = [r for r in rows if r['ok']]
    out[season] = dict(sampled=len(rows), ok=len(ok), with_inactives=sum(1 for r in ok if r['inactives'] > 0), mean_inactives=round(sum(r['inactives'] for r in ok) / max(len(ok), 1), 2), games=rows)
derive.run(con); ing.finish('ok')
(ROOT / 'data' / 'discovery' / 'inactives_coverage.json').write_text(json.dumps(out, indent=1, sort_keys=True) + '\n')
for s, d in out.items():
    print(s, {k: v for k, v in d.items() if k != 'games'}, [(g['game_date'], g['inactives']) for g in d['games'] if g['ok']])
