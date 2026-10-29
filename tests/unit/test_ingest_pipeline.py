import pytest
from nba_props.storage.db import connect
from nba_props.ingestion.runner import Ingestor
from nba_props.api.client import NBAClient
from tests.conftest import make_factory


def mk(raw_fx, tmp_path, calls=None, fail=None, pacing=0.0):
    con = connect(':memory:')
    client = NBAClient(raw_dir=tmp_path, factory=make_factory(raw_fx, calls, fail), pacing_s=pacing, max_workers=1, backoff_s=0.0, sleep=lambda s: None)
    return con, Ingestor(con, client, command='test')


def counts(con):
    return {t: con.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in ('games', 'player_game', 'team_game', 'player_advanced_game', 'team_advanced_game', 'teams', 'players')}


def test_ingest_season_loads_all_tables(raw_fx, tmp_path):
    con, ing = mk(raw_fx, tmp_path)
    out = ing.ingest_season('2025-26')
    c = counts(con)
    assert c['team_game'] == 12 and c['games'] == 6 and c['team_advanced_game'] == 12
    assert c['player_game'] == c['player_advanced_game'] > 100
    assert out['schedule_games'] == 6


def test_ids_stay_strings_with_leading_zeros(raw_fx, tmp_path):
    con, ing = mk(raw_fx, tmp_path); ing.ingest_season('2025-26')
    ids = [r[0] for r in con.execute('SELECT DISTINCT game_id FROM player_game').fetchall()]
    assert all(isinstance(i, str) and len(i) == 10 and i.startswith('00') for i in ids)
    assert con.execute("SELECT count(*) FROM player_game WHERE player_id LIKE '%.%'").fetchone()[0] == 0


def test_repeated_ingestion_is_idempotent(raw_fx, tmp_path):
    con, ing = mk(raw_fx, tmp_path)
    ing.ingest_season('2025-26'); a = counts(con)
    snap = con.execute('SELECT * FROM player_game ORDER BY game_id, player_id').df()
    ing.ingest_season('2025-26', refresh=True); ing.ingest_season('2025-26', refresh=True)
    assert counts(con) == a
    import pandas as pd
    pd.testing.assert_frame_equal(snap, con.execute('SELECT * FROM player_game ORDER BY game_id, player_id').df())


def test_reingesting_one_source_does_not_wipe_columns_from_another(raw_fx, tmp_path):
    con, ing = mk(raw_fx, tmp_path); ing.ingest_season('2025-26')
    assert con.execute('SELECT count(*) FROM player_game WHERE min_sec IS NOT NULL').fetchone()[0] > 100
    # re-ingest ONLY the league log (fails every other endpoint) - min_sec / min_exact must survive
    def fail(e, p): 
        if e != 'LeagueGameLog': raise TimeoutError('down')
    con2_calls = []
    ing.client._factory = make_factory(raw_fx, con2_calls, fail); ing.client.max_retries = 1
    ing.ingest_season('2025-26', refresh=True)
    assert con.execute('SELECT count(*) FROM player_game WHERE min_sec IS NOT NULL').fetchone()[0] > 100
    assert con.execute('SELECT count(*) FROM player_game WHERE min_exact IS NULL').fetchone()[0] == 0


def test_partial_failure_is_recorded_and_run_continues(raw_fx, tmp_path):
    def fail(e, p):
        if e == 'ScheduleLeagueV2': raise TimeoutError('schedule down')
    con, ing = mk(raw_fx, tmp_path, fail=fail); ing.client.max_retries = 2
    ing.ingest_season('2025-26')
    assert counts(con)['player_game'] > 100                         # the rest still loaded
    assert con.execute("SELECT count(*) FROM source_requests WHERE endpoint='ScheduleLeagueV2' AND NOT ok").fetchone()[0] == 1
    assert con.execute("SELECT count(*) FROM games WHERE NOT in_schedule AND in_gamelog").fetchone()[0] == 6   # games reconstructed from box scores, flagged as not in schedule


def test_api_schema_change_is_loud_and_recorded(raw_fx, tmp_path):
    import copy
    bad = copy.deepcopy(raw_fx['league_P'])
    rs = bad['resultSets'][0]; i = rs['headers'].index('PTS')
    rs['headers'][i] = 'POINTS'                                      # API renamed a column
    fx = dict(raw_fx, league_P=bad)
    con, ing = mk(fx, tmp_path); ing.ingest_season('2025-26')
    assert counts(con)['player_game'] == 0
    r = con.execute("SELECT check_name, severity, passed FROM data_quality_results WHERE check_name='schema_drift'").fetchall()
    assert r and r[0][1] == 'error' and r[0][2] is False


def test_boxscore_ingest_resumes_after_interruption(raw_fx, tmp_path):
    games = raw_fx['games']
    con, ing = mk(raw_fx, tmp_path); ing.ingest_season('2025-26')
    seen = []
    def stop_after_three(e, p):
        seen.append(p['game_id'])
        if len(seen) == 4: raise KeyboardInterrupt
    ing.client._factory = make_factory(raw_fx, None, stop_after_three)
    with pytest.raises(KeyboardInterrupt):
        ing.ingest_boxscores('2025-26', inactives=False, batch=2)
    done1 = con.execute('SELECT count(DISTINCT game_id) FROM historical_starters').fetchone()[0]
    assert 0 < done1 < len(games), 'the first committed batch must survive the interruption'
    calls = []
    ing.client._factory = make_factory(raw_fx, calls)
    ing.ingest_boxscores('2025-26', inactives=False, batch=2)
    assert con.execute('SELECT count(DISTINCT game_id) FROM historical_starters').fetchone()[0] == len(games)
    assert len(calls) == len(games) - done1, 'resume must fetch only the games still missing'
    assert con.execute("SELECT count(*) - count(DISTINCT game_id||'|'||player_id) FROM historical_starters").fetchone()[0] == 0
    n = con.execute('SELECT count(*) FROM historical_starters').fetchone()[0]
    ing.ingest_boxscores('2025-26', inactives=False)                  # nothing left: no calls, no duplicates
    assert con.execute('SELECT count(*) FROM historical_starters').fetchone()[0] == n


def test_starters_are_exactly_five_per_team_from_real_responses(raw_fx, tmp_path):
    con, ing = mk(raw_fx, tmp_path); ing.ingest_season('2025-26'); ing.ingest_boxscores('2025-26', inactives=False)
    rows = con.execute('SELECT game_id, team_id, sum(started::int) n FROM historical_starters GROUP BY 1,2').fetchall()
    assert len(rows) == 12 and all(r[2] == 5 for r in rows)
    assert con.execute("SELECT count(*) FROM player_appearances WHERE status='CONFIRMED_DNP'").fetchone()[0] >= 1


def test_summary_inactives_parse(raw_fx, tmp_path):
    from nba_props.api.client import parse_frames
    from nba_props.ingestion import normalize as N
    fr = parse_frames('BoxScoreSummaryV3', {'game_id': '0022600143'}, raw_fx['summary_v3'])
    df = N.inactives(fr['InactivePlayers'], '2026-10-29T16:00:00+00:00')
    assert len(df) == 12 and df.player_id.map(type).eq(str).all() and df.team_id.nunique() == 2
