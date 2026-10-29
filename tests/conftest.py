import json, sys
from pathlib import Path
import duckdb, pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'scripts'))
FX = ROOT / 'tests' / 'fixtures'


def pytest_collection_modifyitems(config, items):
    import os
    live = os.environ.get('NBA_PROPS_LIVE') == '1'
    have_db = (ROOT / 'data' / 'warehouse' / 'nba.duckdb').exists()
    for it in items:
        if it.get_closest_marker('integration') and not live:
            it.add_marker(pytest.mark.skip(reason='set NBA_PROPS_LIVE=1 to run live-API tests'))
        if it.get_closest_marker('realdata') and not have_db:
            it.add_marker(pytest.mark.skip(reason='no local real warehouse'))


def load_fixture_db(con=None):
    """In-memory warehouse populated from the committed REAL-data parquet fixtures (two date windows)."""
    from nba_props.storage.db import connect
    from nba_props.ingestion import derive
    con = con or connect(':memory:')
    for t in ('games', 'player_game', 'team_game', 'player_advanced_game', 'team_advanced_game', 'historical_starters', 'historical_inactives'):
        con.execute(f"INSERT INTO {t} BY NAME SELECT * FROM read_parquet('{(FX / 'warehouse' / (t + '.parquet')).as_posix()}')")
    derive.run(con)
    return con


@pytest.fixture(scope='session')
def fx_con():
    """Shared read-mostly fixture warehouse. Tests that mutate must use `fx_copy`."""
    return load_fixture_db()


@pytest.fixture()
def fx_copy():
    return load_fixture_db()


@pytest.fixture(scope='session')
def raw_fx():
    d = FX / 'raw'
    return {p.stem: json.loads(p.read_text()) for p in d.glob('*.json')}


def make_factory(raw_fx, calls=None, fail=None):
    """Fake network layer: (endpoint, params, timeout) -> raw dict from the REAL trimmed responses. `fail(endpoint, params)` may raise."""
    def factory(endpoint, params, timeout):
        if calls is not None:
            calls.append((endpoint, dict(params)))
        if fail:
            fail(endpoint, params)
        if endpoint == 'LeagueGameLog':
            return raw_fx['league_' + params['player_or_team_abbreviation']]
        if endpoint in ('PlayerGameLogs', 'TeamGameLogs'):
            tag = 'pgl' if endpoint == 'PlayerGameLogs' else 'tgl'
            return raw_fx[f"{tag}_{params['measure_type_player_game_logs_nullable'].lower()}"]
        if endpoint == 'ScheduleLeagueV2':
            return raw_fx['schedule']
        if endpoint == 'BoxScoreTraditionalV3':
            return raw_fx[f"boxscore_v3_{params['game_id']}"]
        if endpoint == 'BoxScoreSummaryV3':
            return raw_fx['summary_v3']
        raise RuntimeError(f'unexpected endpoint {endpoint}')
    return factory
