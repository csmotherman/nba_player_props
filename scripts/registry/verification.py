"""Six-level verification matrix per feature. Levels are NEVER collapsed into one 'verified' flag:

  source_schema      columns exist in observed live responses (enforced by checks.py)
  identity           mathematical identity vs an API-provided column (data/discovery/formula_checks.json; real warehouse data)
  aggregation_impl   the rolling/aggregation implementation exists in nba_props and is unit-tested
  historical_cover   seasons actually loaded and checked in the warehouse
  point_in_time_impl as-of semantics implemented and covered by leakage + time-travel tests
  forecast_accuracy  out-of-sample predictive accuracy (nothing is validated at this level yet)

Correlation is never used as evidence of equality.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
EVIDENCE_FILE = ROOT / 'data' / 'discovery' / 'formula_checks.json'
WAREHOUSE_SOURCES = {'LeagueGameLog', 'PlayerGameLogs', 'TeamGameLogs', 'ScheduleLeagueV2', 'BoxScoreTraditionalV3'}
WAREHOUSE_SEASONS = '2023-24..2026-27 regular season (2026-27 in progress)'

# feature -> identity check that tests EXACTLY the quantity the feature defines
IDENTITY = {
    'BOX_TS_PCT': 'ts_pct', 'SHT_TS_ROLL': 'ts_pct', 'SHT_PTS_PER_SHOT': 'ts_pct',
    'BOX_USG_PCT': 'usg_pct', 'USG_USG_FORMULA': 'usg_pct',
    'BOX_AST_PCT': 'ast_pct', 'BOX_REB_PCT': 'reb_pct', 'BOX_OREB_PCT': 'oreb_pct', 'BOX_DREB_PCT': 'dreb_pct',
    'BOX_TM_TOV_PCT': 'tm_tov_pct_api_definition',
    'BOX_POSS': 'player_poss_vs_oncourt_pace',
    'POS_TEAM_POSS_OBSERVED': 'team_poss_oliver_vs_api',
    'POS_TEAM_PACE_ROLL': 'team_pace_from_api_poss',
    'REB_AVAILABLE_MISSES_TEAM': 'rebound_supply_fit',
    'LBL_MIN': 'min_vs_min_sec',
}
# evidence about a DIFFERENT (related) quantity: deliberately NOT counted as identity evidence
RELATED_ONLY = {
    'TOV_RATE': ('tm_tov_pct_api_definition', 'TOV_RATE is turnovers per 100 possessions; the check tests the API TM_TOV_PCT ratio, a different quantity. No external ground truth exists for TOV_RATE.'),
    'POS_ONCOURT_FACTOR': ('player_poss_vs_oncourt_pace', 'the factor is a fitted ratio of player to team possessions; the check tests POSS ~ PACE*MIN/48, a related identity'),
    'AST_PCT_ROLL': ('ast_pct', 'rolling minutes-weighted AST% is not the single-game identity'),
    'REB_PCT_ROLL': ('reb_pct', 'rolling REB% is not the single-game identity'),
    'USG_ROLL': ('usg_pct', 'rolling usage is not the single-game identity'),
}


TEST_FILE = ROOT / 'data' / 'discovery' / 'test_results.json'
REQUIRED_TEST_FILES = ('test_asof_features.py', 'test_synthetic_scenarios.py', 'test_warehouse_integrity.py')


def pit_tests_passed():
    """True only if the recorded offline run passed and covered the time-travel/leakage/integrity files with zero failures."""
    if not TEST_FILE.exists():
        return False
    t = json.loads(TEST_FILE.read_text())
    if t.get('returncode') != 0:
        return False
    by = {k.split('/')[-1]: v for k, v in t.get('by_file', {}).items()}
    return all(f in by and by[f]['PASSED'] > 0 and by[f]['FAILED'] == 0 and by[f]['ERROR'] == 0 for f in REQUIRED_TEST_FILES)


def load_evidence():
    return json.loads(EVIDENCE_FILE.read_text()) if EVIDENCE_FILE.exists() else {'identities': {}}


def matrix(f, implemented, evidence):
    """-> dict of the six levels (strings) + implementation_status for feature dict f."""
    ev = evidence.get('identities', {})
    fid = f['id']
    schema = 'verified' if f['source_columns'] and f['validation_status'] not in ('unverified_source', 'external_unobtained') else (
        'n/a (no source columns)' if not f['source_columns'] else 'unverified')
    if fid in IDENTITY:
        c = ev.get(IDENTITY[fid])
        ident = f"{c['verdict']} (check={IDENTITY[fid]}, n={c['n']}, MAE={c['mae']:.4g}, bias={c['bias']:+.3g}, max={c['max_abs']:.3g}, exceptions={c['n_exceptions']})" if c else 'untested (evidence file missing)'
    elif fid in RELATED_ONLY:
        ident = f'untested: {RELATED_ONLY[fid][1]}'
    elif f['classification'] == 'RAW' or f['temporal_status'] == 'label':
        ident = 'n/a (raw column)'
    else:
        ident = 'untested'
    srcs = {s.split('[')[0].strip() for s in f['source_endpoints']}
    if srcs and srcs <= WAREHOUSE_SOURCES:
        cover = f'verified in warehouse: {WAREHOUSE_SEASONS}'
    elif 'Verified' in f['historical_availability'] or 'verified' in f['historical_availability']:
        cover = 'partial: discovery samples only (see historical_availability)'
    else:
        cover = 'untested'
    impl = fid in implemented
    return dict(source_schema=schema, identity=ident, aggregation_impl=('verified (nba_props, offline tests)' if pit_tests_passed() else 'implemented, tests not recorded as passing') if impl else 'untested',
                historical_coverage=cover, point_in_time_impl='verified (time-travel + leakage tests)' if impl else 'untested',
                forecast_accuracy='untested')


def summary_status(f, mx, implemented):
    declared = f['validation_status']
    if declared in ('unverified_source', 'external_unobtained'):
        return declared
    if f['id'] in implemented:
        return 'implemented_pit_verified' if pit_tests_passed() else 'source_verified_untested_logic'
    ident = mx['identity']
    if ident.startswith(('exact_within_rounding', 'exact_with_exceptions')):
        return 'identity_verified'
    if ident.startswith('approximate'):
        return 'identity_approximate'
    return declared
