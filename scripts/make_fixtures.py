"""Build small, deterministic, REAL-data fixtures for offline tests from the local warehouse + raw store.

    python scripts/make_fixtures.py
Writes tests/fixtures/warehouse/*.parquet (two date windows of real rows) and tests/fixtures/raw/*.json (trimmed real API responses).
Nothing synthetic is generated here; synthetic edge cases live in the tests themselves and are labelled as such.
"""
import gzip, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent; sys.path.insert(0, str(ROOT))
import duckdb
from nba_props.storage.db import connect

WINDOWS = [('2024-25', '2025-03-25', '2025-04-13'), ('2025-26', '2025-10-21', '2025-11-20')]
OUT = ROOT / 'tests' / 'fixtures'
(OUT / 'warehouse').mkdir(parents=True, exist_ok=True); (OUT / 'raw').mkdir(parents=True, exist_ok=True)
con = connect(read_only=True)
cond = ' OR '.join(f"(g.season='{s}' AND g.game_date BETWEEN DATE '{a}' AND DATE '{b}')" for s, a, b in WINDOWS)
con.execute(f"CREATE TEMP TABLE fx_games AS SELECT g.* FROM games g WHERE g.season_type='regular' AND g.in_gamelog AND ({cond})")
tables = {
    'games': "SELECT * FROM fx_games ORDER BY game_id",
    'player_game': "SELECT p.* FROM player_game p JOIN fx_games USING(game_id) ORDER BY game_id, player_id",
    'team_game': "SELECT t.* FROM team_game t JOIN fx_games USING(game_id) ORDER BY game_id, team_id",
    'player_advanced_game': "SELECT a.* FROM player_advanced_game a JOIN fx_games USING(game_id) ORDER BY game_id, player_id",
    'team_advanced_game': "SELECT a.* FROM team_advanced_game a JOIN fx_games USING(game_id) ORDER BY game_id, team_id",
    'historical_starters': "SELECT h.* EXCLUDE (fetched_at) FROM historical_starters h JOIN fx_games USING(game_id) ORDER BY game_id, player_id",
    'historical_inactives': "SELECT h.* EXCLUDE (fetched_at) FROM historical_inactives h JOIN fx_games USING(game_id) ORDER BY game_id, player_id",
}
for name, sql in tables.items():
    df = con.execute(sql).df()
    df.to_parquet(OUT / 'warehouse' / f'{name}.parquet', index=False, compression='zstd')
    print(f'{name:22s} {len(df):7d} rows')

# ---- trimmed REAL raw API responses (same 6 games everywhere so cross-source joins are consistent) ----
games = [r[0] for r in con.execute("""SELECT g.game_id FROM games g WHERE g.season='2025-26' AND g.season_type='regular' AND g.in_gamelog
    AND g.game_id IN (SELECT game_id FROM historical_starters) AND g.game_date BETWEEN DATE '2025-10-21' AND DATE '2025-10-23' ORDER BY g.game_id LIMIT 6""").fetchall()]
def raw(ep, pred):
    for f in sorted((ROOT / 'data' / 'raw' / ep).glob('*.json.gz')):
        d = json.loads(gzip.decompress(f.read_bytes()))
        if pred(d):
            return d
def trim_classic(d, name, idx_col):
    for rs in d['resultSets']:
        i = rs['headers'].index(idx_col)
        rs['rowSet'] = [r for r in rs['rowSet'] if str(r[i]) in games]
    return d
cfg = {
    'league_P': ('LeagueGameLog', lambda d: d['parameters'].get('PlayerOrTeam') == 'P' and d['parameters'].get('Season') == '2025-26' and d['parameters'].get('SeasonType') == 'Regular Season', 'GAME_ID'),
    'league_T': ('LeagueGameLog', lambda d: d['parameters'].get('PlayerOrTeam') == 'T' and d['parameters'].get('Season') == '2025-26' and d['parameters'].get('SeasonType') == 'Regular Season', 'GAME_ID'),
}
for name, (ep, pred, col) in cfg.items():
    d = raw(ep, pred)
    (OUT / 'raw' / f'{name}.json').write_text(json.dumps(trim_classic(d, name, col), sort_keys=True))
def pgl(mt, ep):
    return raw(ep, lambda d: d['parameters'].get('SeasonYear') == '2025-26' and d['parameters'].get('MeasureType') == mt and d['parameters'].get('SeasonType') == 'Regular Season')
for ep, tag in (('PlayerGameLogs', 'pgl'), ('TeamGameLogs', 'tgl')):
    for mt in ('Base', 'Advanced'):
        d = pgl(mt, ep)
        if d is None:
            print('missing raw', ep, mt); continue
        (OUT / 'raw' / f'{tag}_{mt.lower()}.json').write_text(json.dumps(trim_classic(d, tag, 'GAME_ID'), sort_keys=True))
d = raw('ScheduleLeagueV2', lambda d: d['leagueSchedule']['seasonYear'].startswith('2025'))
ls = d['leagueSchedule']
ls['gameDates'] = [{'gameDate': gd['gameDate'], 'games': [g for g in gd['games'] if g['gameId'] in games]} for gd in ls['gameDates']]
ls['gameDates'] = [gd for gd in ls['gameDates'] if gd['games']]; ls['weeks'] = []
(OUT / 'raw' / 'schedule.json').write_text(json.dumps(d, sort_keys=True))
from nba_props.api.client import parse_frames
for f in sorted((ROOT / 'data' / 'raw' / 'BoxScoreTraditionalV3').glob('*.json.gz')):
    dd = json.loads(gzip.decompress(f.read_bytes()))
    if dd['boxScoreTraditional']['gameId'] in games:
        (OUT / 'raw' / f"boxscore_v3_{dd['boxScoreTraditional']['gameId']}.json").write_text(json.dumps(dd, sort_keys=True))
best = None                       # the summary response with the most inactive players (REAL, from the in-progress season)
for f in sorted((ROOT / 'data' / 'raw' / 'BoxScoreSummaryV3').glob('*.json.gz')):
    dd = json.loads(gzip.decompress(f.read_bytes()))
    n = len(parse_frames('BoxScoreSummaryV3', {'game_id': dd['boxScoreSummary']['gameId']}, dd)['InactivePlayers'])
    if best is None or n > best[0]:
        best = (n, dd)
(OUT / 'raw' / 'summary_v3.json').write_text(json.dumps(best[1], sort_keys=True)); print('summary fixture inactives:', best[0], best[1]['boxScoreSummary']['gameId'])
(OUT / 'raw' / 'games.json').write_text(json.dumps(games))
print('raw fixture games', games)
