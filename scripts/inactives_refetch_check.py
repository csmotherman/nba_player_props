"""For 2026-27 games whose first summary fetch had no inactives, refetch NOW and compare: late-populating feed or permanently empty?
Writes data/discovery/inactives_refetch.json."""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent; sys.path.insert(0, str(ROOT))
from nba_props.storage.db import connect, upsert
from nba_props.ingestion.runner import Ingestor
from nba_props.ingestion import normalize as N, derive
con = connect(); ing = Ingestor(con, command='inactives-refetch')
gids = [r[0] for r in con.execute("""SELECT g.game_id FROM games g WHERE g.season='2026-27' AND g.in_gamelog AND NOT EXISTS (SELECT 1 FROM historical_inactives i WHERE i.game_id=g.game_id)
                                     AND g.game_id IN (SELECT json_extract_string(params_json,'$.game_id') FROM source_requests WHERE endpoint='BoxScoreSummaryV3' AND ok) ORDER BY g.game_id""").fetchall()]
rows = []
for gid in gids:
    first = con.execute("SELECT min(fetched_at) FROM source_requests WHERE endpoint='BoxScoreSummaryV3' AND json_extract_string(params_json,'$.game_id')=?", [gid]).fetchall()[0][0]
    fr, at = ing.get('BoxScoreSummaryV3', {'game_id': gid}, '2026-27', refresh=True)
    n = 0 if fr is None else len(fr['InactivePlayers'])
    if n: upsert(con, 'historical_inactives', N.inactives(fr['InactivePlayers'], at))
    rows.append(dict(game_id=gid, first_fetch=str(first), refetch=str(at), inactives_now=n))
derive.run(con); ing.finish('ok')
res = dict(games_empty_at_first_fetch=len(rows), populated_on_refetch=sum(1 for r in rows if r['inactives_now'] > 0), still_empty=sum(1 for r in rows if r['inactives_now'] == 0), games=rows)
(ROOT / 'data' / 'discovery' / 'inactives_refetch.json').write_text(json.dumps(res, indent=1, sort_keys=True) + '\n')
print({k: v for k, v in res.items() if k != 'games'})
