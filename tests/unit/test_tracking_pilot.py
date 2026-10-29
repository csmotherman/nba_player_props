"""Pilot LOGIC tests on SYNTHETIC frames (labelled). Real pilot results come from `python -m nba_props tracking-pilot`."""
import pandas as pd, pytest
from nba_props.tracking import pilot
from nba_props.api.guards import LeakageGuardError


def tr(**kw):
    return pd.DataFrame(kw)


def test_compare_exact_match_and_flags():
    t = tr(PLAYER_ID=[1, 2, 3], GP=[1, 1, 1], AST=[5, 0, 7], POTENTIAL_AST=[9, 1, 7])
    b = tr(PLAYER_ID=['1', '2', '3'], MIN=[30, 10, 25], AST=[5, 0, 7])
    r = pilot.compare(t, b, 'Passing')
    assert r['match_rate'] == 1.0 and r['dup_player_ids'] == 0 and r['gp_max'] == 1 and r['potential_ge_assists']


def test_compare_detects_mismatch_duplicates_and_missing_players():
    t = tr(PLAYER_ID=[1, 1, 2], GP=[1, 2, 1], AST=[5, 5, 1], POTENTIAL_AST=[9, 9, 0])
    b = tr(PLAYER_ID=['1', '2', '4'], MIN=[30, 10, 25], AST=[5, 3, 2])
    r = pilot.compare(t, b, 'Passing')
    assert r['dup_player_ids'] == 1 and r['gp_max'] == 2 and r['match_rate'] < 1 and r['only_in_box'] == 1 and not r['potential_ge_assists']


def test_compare_ignores_zero_minute_box_rows():
    t = tr(PLAYER_ID=[1], GP=[1], AST=[1], POTENTIAL_AST=[2])
    b = tr(PLAYER_ID=['1', '9'], MIN=[20, 0], AST=[1, 0])
    assert pilot.compare(t, b, 'Passing')['only_in_box'] == 0


def test_empty_windows_are_handled_not_crashed():
    r = pilot.compare(tr(PLAYER_ID=[], GP=[], AST=[]), tr(PLAYER_ID=[], MIN=[], AST=[]), 'Passing')
    assert r['track_rows'] == 0 and r['match_rate'] is None


def test_window_additivity():
    a = tr(PLAYER_ID=['1', '2'], X=[1, 2]); b = tr(PLAYER_ID=['1', '3'], X=[4, 5]); ab = tr(PLAYER_ID=['1', '2', '3'], X=[5, 2, 5])
    assert pilot.window_additivity(a, b, ab, 'X')['equal_share'] == 1.0
    ab_bad = tr(PLAYER_ID=['1', '2', '3'], X=[4, 2, 5])
    assert pilot.window_additivity(a, b, ab_bad, 'X')['equal_share'] < 1.0


def test_pilot_run_with_injected_fetch_labels_verdicts():
    box = tr(PLAYER_ID=['1', '2'], MIN=[30, 20], AST=[5, 2], REB=[4, 6], PTS=[10, 12])
    def fetch(endpoint, params):
        if endpoint == 'LeagueGameLog': return {'LeagueGameLog': box}
        return {'LeagueDashPtStats': tr(PLAYER_ID=[1, 2], GP=[1, 1], AST=[5, 2], POTENTIAL_AST=[8, 3], REB=[4, 6], OREB=[1, 2], DREB=[3, 4], REB_CHANCES=[9, 9], POINTS=[10, 12])}
    p = pilot.Pilot(fetch=fetch)
    row = p.one('2025-26', '2026-01-15', 'Passing')
    assert row['verdict'] == 'exact'
    assert p.one('2025-26', '2026-01-15', 'Rebounding')['oreb_dreb_sum_ok']


def test_pilot_refuses_unbounded_season_aggregates():
    p = pilot.Pilot(fetch=lambda e, q: {})
    with pytest.raises(LeakageGuardError):
        p.get('LeagueDashPtStats', {'season': '2025-26'})


def test_cost_estimate_scales_with_requests():
    c = pilot.estimate_cost([1.0, 2.0], n_seasons=12, dates_per_season=165, n_measures=3, pacing_s=1.5)
    assert c['requests'] == 5940 and c['hours_at_current_pacing'] == pytest.approx(5940 * 1.5 / 3600, abs=0.01)
