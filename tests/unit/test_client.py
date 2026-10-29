import threading, time
import pytest
from nba_props.api.client import NBAClient, parse_frames, params_hash
from nba_props.api.guards import require_cutoff, LeakageGuardError
from tests.conftest import make_factory


class Clock:
    """Deterministic clock + sleep so pacing/backoff tests take no real time."""
    def __init__(self):
        self.t = 0.0; self.sleeps = []
    def now(self): return self.t
    def sleep(self, s): self.sleeps.append(s); self.t += s


def client(tmp_path, factory, clk=None, **kw):
    clk = clk or Clock()
    return NBAClient(raw_dir=tmp_path, factory=factory, sleep=clk.sleep, clock=clk.now, backoff_s=2.0, **kw), clk


def test_pacing_enforces_minimum_interval(tmp_path):
    c, clk = client(tmp_path, lambda e, p, t: {'resultSets': [], 'i': p['i']}, pacing_s=1.5)
    for i in range(5):
        assert c.fetch('X', {'i': i}).ok
    assert clk.t >= 4 * 1.5 - 1e-9, 'requests must be spaced by the pacing interval'


def test_retry_with_exponential_backoff_then_success(tmp_path):
    n = {'k': 0}
    def f(e, p, t):
        n['k'] += 1
        if n['k'] < 3: raise TimeoutError('read timed out')
        return {'ok': 1}
    c, clk = client(tmp_path, f, pacing_s=0.0, max_retries=4)
    r = c.fetch('X', {})
    assert r.ok and r.attempts == 3
    backoffs = [s for s in clk.sleeps if s >= 1.0]
    assert len(backoffs) == 2 and backoffs[1] > backoffs[0], 'backoff must grow'


def test_exhausted_retries_report_failure_not_exception(tmp_path):
    c, _ = client(tmp_path, lambda e, p, t: (_ for _ in ()).throw(ConnectionError('boom')), pacing_s=0.0, max_retries=3)
    r = c.fetch('X', {})
    assert not r.ok and r.attempts == 3 and 'ConnectionError' in r.error


def test_bad_parameter_is_not_retried(tmp_path):
    calls = []
    def f(e, p, t): calls.append(1); raise TypeError("unexpected keyword 'foo'")
    c, _ = client(tmp_path, f, pacing_s=0.0)
    r = c.fetch('X', {})
    assert not r.ok and len(calls) == 1


def test_circuit_breaker_cools_down_globally(tmp_path):
    fails = {'on': True}
    def f(e, p, t):
        if fails['on']: raise TimeoutError('x')
        return {'ok': 1}
    c, clk = client(tmp_path, f, pacing_s=0.1, max_retries=1)
    for i in range(3):
        c.fetch('X', {'i': i})                         # 3 consecutive failures -> breaker trips
    fails['on'] = False
    before = clk.t
    assert c.fetch('X', {'i': 99}).ok
    assert clk.t - before >= 60 - 1e-6, 'next request must wait for the cooldown'


def test_bounded_concurrency(tmp_path):
    lock, state = threading.Lock(), {'cur': 0, 'max': 0}
    def f(e, p, t):
        with lock:
            state['cur'] += 1; state['max'] = max(state['max'], state['cur'])
        time.sleep(0.02)
        with lock:
            state['cur'] -= 1
        return {'i': p['i']}
    c = NBAClient(raw_dir=tmp_path, factory=f, pacing_s=0.0, max_workers=2)
    res = list(c.fetch_many([('X', {'i': i}) for i in range(12)]))
    assert len(res) == 12 and all(r.ok for r in res) and state['max'] <= 2


def test_raw_store_is_content_addressed_atomic_and_idempotent(tmp_path):
    c, _ = client(tmp_path, lambda e, p, t: {'a': [1, 2, 3]}, pacing_s=0.0)
    r1, r2 = c.fetch('X', {'q': 1}), c.fetch('X', {'q': 2})        # different params, identical payload
    assert r1.sha256 == r2.sha256 and r1.raw_path == r2.raw_path
    files = list((tmp_path / 'X').iterdir())
    assert len(files) == 1 and not any(f.suffix == '.tmp' for f in files)
    assert NBAClient.load_raw(r1.raw_path) == {'a': [1, 2, 3]}


def test_params_hash_is_stable_and_order_independent():
    assert params_hash('E', {'a': 1, 'b': 2}) == params_hash('E', {'b': 2, 'a': 1})
    assert params_hash('E', {'a': 1}) != params_hash('F', {'a': 1})


def test_replay_parses_stored_real_response(raw_fx):
    fr = parse_frames('LeagueGameLog', {'season': '2025-26', 'player_or_team_abbreviation': 'P'}, raw_fx['league_P'])
    df = fr['LeagueGameLog']
    assert len(df) > 100 and df.GAME_ID.str.startswith('00225').all()
    assert df.GAME_ID.str.len().eq(10).all(), 'game ids keep their leading zeros'


@pytest.mark.parametrize('endpoint', ['LeagueDashPlayerStats', 'LeagueDashPtStats', 'TeamPlayerOnOffSummary', 'LeagueDashLineups'])
def test_season_aggregate_endpoint_requires_date_cutoff(endpoint):
    with pytest.raises(LeakageGuardError):
        require_cutoff(endpoint, {'season': '2025-26'})
    require_cutoff(endpoint, {'season': '2025-26', 'date_to_nullable': '2026-01-14'})


@pytest.mark.parametrize('endpoint', ['LeagueStandingsV3', 'CommonTeamRoster', 'PlayerIndex', 'GravityLeaders'])
def test_snapshot_only_endpoints_are_refused_for_history(endpoint):
    with pytest.raises(LeakageGuardError):
        require_cutoff(endpoint, {'season': '2025-26', 'date_to_nullable': '2026-01-14'})


def test_game_level_endpoints_are_not_blocked():
    require_cutoff('BoxScoreTraditionalV3', {'game_id': '0022500001'})
    require_cutoff('LeagueGameLog', {'season': '2025-26'})
