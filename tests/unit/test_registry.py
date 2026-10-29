"""Registry validator (adversarial), readiness semantics, verification matrix, decoupling, determinism."""
import copy, filecmp, json, os, subprocess, sys
from pathlib import Path
import pytest
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import registry
from registry import checks, readiness
from registry.fallbacks import FALLBACKS

DISC = str(ROOT / 'data' / 'discovery')


def node(i, t, deps=(), opt=(), cls='CALCULATED'):
    return dict(id=i, temporal_status=t, dependencies=list(deps), optional_dependencies=list(opt), classification=cls)


def graph(*nodes):
    return {n['id']: n for n in nodes}


# ------------------------------------------------------------------ B. leakage validator, adversarial (SYNTHETIC graphs)
def test_direct_label_dependency_is_flagged():
    g = graph(node('P', 'projected', ['L']), node('L', 'label'))
    assert checks.label_leaks(g, 'P') == ['P', 'L']


def test_label_reachable_via_valid_lag_path_only_is_allowed():
    g = graph(node('P', 'projected', ['LAG']), node('LAG', 'lagged_observed', ['L']), node('L', 'label'))
    assert checks.label_leaks(g, 'P') is None


def test_label_reachable_both_validly_and_invalidly_is_flagged_regardless_of_order():
    """The regression for the shared-visited-set bug: valid path explored first must not hide the invalid direct path."""
    for deps in (['LAG', 'BAD'], ['BAD', 'LAG']):
        g = graph(node('P', 'projected', deps), node('LAG', 'lagged_observed', ['L']), node('BAD', 'projected', ['L']), node('L', 'label'))
        assert checks.label_leaks(g, 'P') == ['P', 'BAD', 'L'], deps
    g = graph(node('P', 'projected', ['LAG', 'L']), node('LAG', 'lagged_observed', ['L']), node('L', 'label'))
    assert checks.label_leaks(g, 'P') == ['P', 'L']


def test_label_hidden_behind_a_shared_intermediate_node_is_flagged():
    g = graph(node('P', 'projected', ['A', 'B']), node('A', 'lagged_observed', ['S']), node('B', 'projected', ['S']), node('S', 'projected', ['L']), node('L', 'label'))
    assert checks.label_leaks(g, 'P') == ['P', 'B', 'S', 'L']


def test_optional_dependency_leakage_is_flagged():
    g = graph(node('P', 'projected', ['OK'], opt=['L']), node('OK', 'pregame_known'), node('L', 'label'))
    assert checks.label_leaks(g, 'P') == ['P', 'L']


def test_cycles_terminate_and_do_not_hide_leaks():
    g = graph(node('A', 'projected', ['B']), node('B', 'projected', ['A', 'L']), node('L', 'label'))
    assert checks.label_leaks(g, 'A') == ['A', 'B', 'L']
    g2 = graph(node('A', 'projected', ['B']), node('B', 'projected', ['A']))
    assert checks.label_leaks(g2, 'A') is None


def test_cycle_detected_by_full_validator():
    F = copy.deepcopy(registry.finalize())
    next(f for f in F if f['id'] == 'LBL_MIN')['dependencies'].append('MIN_EXP')
    assert any('cycle' in e for e in checks.run(F, DISC)['errors'])


def test_lagged_feature_may_not_embed_a_projection():
    F = copy.deepcopy(registry.finalize())
    next(f for f in F if f['id'] == 'MIN_ROLL')['dependencies'].append('MIN_EXP')
    assert any('embed a forecast' in e for e in checks.run(F, DISC)['errors'])


def test_real_registry_has_no_label_leak_paths_and_no_errors():
    F = registry.finalize()
    byid = {f['id']: f for f in F}
    for f in F:
        if f['temporal_status'] in ('projected', 'pregame_known', 'external_pregame', 'unverified'):
            assert checks.label_leaks(byid, f['id']) is None, f['id']
    assert checks.run(F, DISC)['errors'] == []


@pytest.mark.parametrize('mutation,needle', [
    (lambda f: f['LBL_PTS']['source_columns'].append('LeagueGameLog.NOT_A_COLUMN'), 'not found'),
    (lambda f: f['MIN_EXP']['dependencies'].append('NOPE'), 'not in registry'),
    (lambda f: f['EXP_FGA']['dependencies'].append('LBL_FGA'), 'reaches a label'),
    (lambda f: f['TOV_RATE'].__setitem__('validation_status', 'identity_verified'), 'identity_verified'),
    (lambda f: f['POS_ONCOURT_FACTOR'].__setitem__('validation_status', 'identity_approximate'), 'identity'),
    (lambda f: f['LBL_PTS'].__setitem__('pregame_availability', 'Yes'), 'label must be'),
    (lambda f: f['POS_TEAM_POSS_OBSERVED'].__setitem__('leakage_risk', 'Low'), 'Low leakage'),
    (lambda f: f['EXP_FGA'].__setitem__('optional_unavailable_without_fallback', ['X']), 'no declared fallback'),
])
def test_validator_catches_injected_defects(mutation, needle):
    F = copy.deepcopy(registry.finalize()); byid = {f['id']: f for f in F}
    mutation(byid)
    errs = checks.run(F, DISC)['errors']
    assert any(needle in e for e in errs), errs


# ------------------------------------------------------------------ A. readiness semantics (SYNTHETIC graphs)
def rf(i, deps=(), opt=(), cls='CALCULATED'):
    return dict(id=i, dependencies=list(deps), optional_dependencies=list(opt), classification=cls)


def test_required_external_dependency_blocks():
    r = readiness.compute([rf('E', cls='EXTERNAL'), rf('A', ['E']), rf('B', ['A'])], {})
    assert r['B']['readiness'] == 'BLOCKED_EXTERNAL' and r['B']['blocking_inputs'] == ['E']


def test_optional_external_dependency_never_blocks_but_is_reported():
    r = readiness.compute([rf('E', cls='EXTERNAL'), rf('A', opt=['E'])], {'A': dict(for_=['E'], text='baseline')})
    assert r['A']['readiness'] == 'EXECUTABLE_NBA_ONLY' and r['A']['optional_unavailable'] == ['E'] and r['A']['optional_unavailable_without_fallback'] == []
    r = readiness.compute([rf('E', cls='EXTERNAL'), rf('A', opt=['E'])], {})
    assert r['A']['optional_unavailable_without_fallback'] == ['E'], 'an undeclared fallback is surfaced (and the validator turns it into an error)'


def test_declared_fallback_turns_block_into_degraded_and_propagates_as_degraded_not_blocked():
    fb = {'A': dict(for_=['E'], text='ok')}
    r = readiness.compute([rf('E', cls='EXTERNAL'), rf('A', ['E']), rf('B', ['A'])], fb)
    assert r['A']['readiness'] == 'EXECUTABLE_DEGRADED' and r['B']['readiness'] == 'EXECUTABLE_DEGRADED'
    assert r['B']['fallbacks_used'] == ['A:E']


def test_fallback_for_a_different_dependency_does_not_unblock():
    r = readiness.compute([rf('E', cls='EXTERNAL'), rf('E2', cls='EXTERNAL'), rf('A', ['E', 'E2'])], {'A': dict(for_=['E'], text='x')})
    assert r['A']['readiness'] == 'BLOCKED_EXTERNAL' and r['A']['blocking_inputs'] == ['E2']


def test_unverified_dependency_blocks_as_unverified_and_external_dominates():
    r = readiness.compute([rf('U', cls='UNVERIFIED'), rf('E', cls='EXTERNAL'), rf('A', ['U']), rf('B', ['U', 'E'])], {})
    assert r['A']['readiness'] == 'BLOCKED_UNVERIFIED' and r['B']['readiness'] == 'BLOCKED_EXTERNAL'


def test_self_fallback_for_an_external_feature():
    r = readiness.compute([rf('E', cls='EXTERNAL')], {'E': dict(for_=['SELF'], text='omit')})
    assert r['E']['readiness'] == 'EXECUTABLE_DEGRADED'


def test_real_p0_chain_is_degraded_not_available_and_not_blocked():
    F = registry.finalize(); R = {f['id']: f for f in F}
    assert R['EXT_INJURY_REPORT']['readiness'] == 'BLOCKED_EXTERNAL'
    for i in ('AVL_TEAMMATE_OUT_USAGE', 'USGR_MINUTES_VACANCY', 'MIN_EXP', 'EXP_FGA', 'EXP_PTS_DIST', 'EXP_REB_BASELINE', 'EXP_AST_BASELINE'):
        assert R[i]['readiness'] == 'EXECUTABLE_DEGRADED', i
        assert 'AVL_TEAMMATE_OUT_USAGE:SELF' in R[i]['fallbacks_used']
    assert R['MIN_ROLL']['readiness'] == 'EXECUTABLE_NBA_ONLY'
    blocked_p0 = [i for i, f in R.items() if f['priority'] == 'P0' and f['readiness'].startswith('BLOCKED')]
    assert sorted(blocked_p0) == ['EXT_INJURY_REPORT', 'EXT_PROP_LINES']


def test_priority_readiness_and_implementation_are_independent_dimensions():
    F = registry.finalize()
    combos = {(f['priority'], f['readiness'].split('_')[0], f['implementation_status']) for f in F}
    assert ('P0', 'EXECUTABLE', 'specified_only') in combos          # important and executable, not yet built
    assert ('P3', 'BLOCKED', 'specified_only') in combos            # unimportant and blocked
    assert any(c[0] == 'P0' and c[1] == 'EXECUTABLE' and c[2].startswith('implemented') for c in combos)
    assert sum(1 for f in F if f['priority'] == 'P0' and f['readiness'] == 'EXECUTABLE_DEGRADED') >= 10


def test_every_optional_unavailable_dependency_has_a_declared_fallback():
    for f in registry.finalize():
        assert f['optional_unavailable_without_fallback'] == [], f['id']
    assert set(FALLBACKS) <= {f['id'] for f in registry.finalize()}


# ------------------------------------------------------------------ C. verification matrix
def test_withdrawn_claims_are_not_identity_verified():
    R = {f['id']: f for f in registry.finalize()}
    assert 'formula_verified' not in {f['validation_status'] for f in R.values()}
    for i in ('TOV_RATE', 'POS_ONCOURT_FACTOR', 'AST_PCT_ROLL', 'REB_PCT_ROLL', 'USG_ROLL'):
        assert R[i]['validation_status'] not in ('identity_verified', 'identity_approximate'), i
        assert R[i]['verification']['identity'].startswith('untested'), i
    assert R['REB_AVAILABLE_MISSES_TEAM']['validation_status'] == 'identity_approximate'
    assert R['POS_TEAM_PACE_ROLL']['verification']['identity'].startswith('approximate')
    for i in ('BOX_USG_PCT', 'BOX_AST_PCT', 'BOX_REB_PCT', 'BOX_POSS', 'POS_TEAM_POSS_OBSERVED'):
        assert R[i]['validation_status'] == 'identity_approximate', i
    for i in ('BOX_TS_PCT', 'SHT_PTS_PER_SHOT', 'LBL_MIN'):
        assert R[i]['validation_status'] == 'identity_verified', i
    assert R['SHT_TS_ROLL']['verification']['aggregation_impl'] == 'untested'     # identity verified, rolling implementation NOT


def test_every_feature_has_all_six_levels_and_forecast_accuracy_is_untested_everywhere():
    for f in registry.finalize():
        assert set(f['verification']) == {'source_schema', 'identity', 'aggregation_impl', 'historical_coverage', 'point_in_time_impl', 'forecast_accuracy'}
        assert f['verification']['forecast_accuracy'] == 'untested'


def test_identity_evidence_records_error_bias_and_sample_size_not_just_correlation():
    ev = json.loads((ROOT / 'data' / 'discovery' / 'formula_checks.json').read_text())['identities']
    for k, v in ev.items():
        assert {'n', 'mae', 'rmse', 'bias', 'max_abs', 'p99_abs', 'within_tol_share', 'verdict'} <= set(v), k
        assert 'corr' not in v


def test_implemented_features_columns_exist_in_the_built_tables():
    from nba_props.features import asof
    from nba_props.features.catalog import IMPLEMENTED
    from tests.conftest import load_fixture_db
    con = load_fixture_db(); asof.build(con, '2025-26', [6])
    cols = {c[0] for t in ('asof_player_features', 'asof_team_features') for c in con.execute(f'DESCRIBE {t}').fetchall()}
    for fid, cs in IMPLEMENTED.items():
        assert set(cs) <= cols, (fid, sorted(set(cs) - cols))


# ------------------------------------------------------------------ D. decoupling of dispersion from prediction outputs
def test_dispersion_features_are_market_specific_and_independent_of_outputs():
    R = {f['id']: f for f in registry.finalize()}
    disp = [i for i in R if i.startswith('VAR_DISP_')]
    assert sorted(disp) == sorted(f'VAR_DISP_{m}' for m in ('PTS', 'REB', 'AST', '3PM', 'STL', 'BLK', 'TOV', 'FGA', 'FG3A'))
    assert 'VAR_NB_DISPERSION' not in R
    byid = R
    def closure(i, seen=None):
        seen = seen if seen is not None else set()
        for d in byid[i]['dependencies'] + byid[i]['optional_dependencies']:
            if d not in seen: seen.add(d); closure(d, seen)
        return seen
    for i in disp:
        c = closure(i)
        assert not [x for x in c if x.startswith(('EXP_', 'ENV_')) or byid[x]['temporal_status'] == 'projected'], (i, sorted(c))
        assert byid[i]['temporal_status'] == 'lagged_observed'


def test_baselines_are_independent_of_other_markets():
    R = {f['id']: f for f in registry.finalize()}
    def closure(i, seen=None):
        seen = seen if seen is not None else set()
        for d in R[i]['dependencies']:
            if d not in seen: seen.add(d); closure(d, seen)
        return seen
    ast, reb = closure('EXP_AST_BASELINE'), closure('EXP_REB_BASELINE')
    assert not {'EXP_FGA', 'EXP_PTS_DIST', 'EXP_3PA', 'EXP_REB_BASELINE', 'VAR_DISP_REB', 'VAR_DISP_PTS'} & ast
    assert not {'EXP_FGA', 'EXP_PTS_DIST', 'EXP_AST_BASELINE', 'VAR_DISP_AST'} & reb
    assert 'VAR_DISP_AST' in ast and 'VAR_DISP_REB' in reb
    assert not ({'EXP_PTS_DIST', 'EXP_REB_BASELINE', 'EXP_AST_BASELINE'} & set(R['VAR_STAT_CORR']['dependencies']))


# ------------------------------------------------------------------ E. determinism: regenerating unchanged definitions changes nothing
def test_generated_artifacts_are_deterministic_and_in_sync(tmp_path):
    env = dict(os.environ, NBA_PROPS_BUILD_OUT=str(tmp_path))
    p = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'build_artifacts.py')], capture_output=True, text=True, env=env, cwd=ROOT)
    assert p.returncode == 0, p.stderr[-2000:] + p.stdout[-500:]
    for name in ('nba_feature_registry.json', 'NBA_FEATURE_CATALOG.csv', 'NBA_FEATURE_READINESS.csv', 'NBA_API_ENDPOINT_INVENTORY.csv', 'NBA_FEATURE_DEPENDENCIES.md', 'nba_feature_explorer.html', 'NBA_DATA_BLUEPRINT.md'):
        assert (tmp_path / name).read_bytes() == (ROOT / name).read_bytes(), f'{name} is stale or non-deterministic: run python scripts/build_artifacts.py'
