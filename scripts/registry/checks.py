"""Executable quality-control checks on the feature registry.

run(features, discovery_dir) -> dict(errors=[...], warnings=[...], info={...})
Build refuses to write artifacts if errors is non-empty.
"""
import json, re, os, glob
from collections import defaultdict

SRC_RE = re.compile(r'^(?P<ep>[A-Za-z0-9]+)(?:\[(?P<var>[^\]]+)\])?\.(?P<col>.+)$')
REQUIRED = ['id', 'name', 'domain', 'description', 'classification', 'temporal_status', 'formula', 'aggregation_level',
            'historical_availability', 'pregame_availability', 'leakage_risk', 'leakage_notes', 'missing_data_handling',
            'validation_method', 'priority', 'validation_status']

# formula_verified claims must be backed by these qc_results.json entries: id -> [(key, field, min_corr_or_max_mae, 'corr'|'mae')]
QC_BACKING = {
    'BOX_USG_PCT': [('usg_formula_vs_api_USG_PCT_fraction_scale', 'corr', 0.98, 'min')],
    'USG_USG_FORMULA': [('usg_formula_vs_api_USG_PCT_fraction_scale', 'corr', 0.98, 'min'), ('usg_formula_vs_api_USG_PCT_fraction_scale', 'mae', 0.02, 'max')],
    'BOX_TS_PCT': [('ts_pct_formula_vs_api', 'corr', 0.999, 'min')],
    'SHT_TS_ROLL': [('ts_pct_formula_vs_api', 'corr', 0.999, 'min')],
    'SHT_PTS_PER_SHOT': [('ts_pct_formula_vs_api', 'corr', 0.999, 'min')],
    'BOX_AST_PCT': [('ast_pct_formula_vs_api', 'corr', 0.95, 'min')],
    'BOX_REB_PCT': [('reb_pct_formula_vs_api', 'corr', 0.95, 'min')],
    'BOX_OREB_PCT': [('oreb_pct_formula_vs_api', 'corr', 0.95, 'min')],
    'BOX_DREB_PCT': [('dreb_pct_formula_vs_api', 'corr', 0.95, 'min')],
    'BOX_TM_TOV_PCT': [('tm_tov_pct_vs_TOV_over_FGA_FTA_AST_TOV_x100', 'corr', 0.99, 'min')],
    'TOV_RATE': [('tm_tov_pct_vs_TOV_over_FGA_FTA_AST_TOV_x100', 'corr', 0.99, 'min')],
    'BOX_POSS': [('player_poss_vs_onCourtPace_x_MIN_over_48', 'corr', 0.99, 'min')],
    'POS_ONCOURT_FACTOR': [('player_poss_vs_onCourtPace_x_MIN_over_48', 'corr', 0.99, 'min')],
    'POS_TEAM_POSS_OBSERVED': [('team_poss_oliver_vs_api', 'corr', 0.95, 'min')],
    'POS_TEAM_PACE_ROLL': [('team_pace_48poss_over_min_vs_api_pace_using_api_poss', None, 1.0, 'scalar_max')],
    'REB_AVAILABLE_MISSES_TEAM': [('rebound_identity', 'corr_reb_vs_fgmiss', 0.85, 'min')],
}


ALIASES = {'PregameBoxSummaryV3': 'BoxScoreSummaryV3', 'PregameBoxTraditionalV3': 'BoxScoreTraditionalV3',
           'PregamePlayByPlayV3': 'PlayByPlayV3', 'Live': 'BoxScore', 'LeagueHustle': 'LeagueHustleStatsPlayer',
           'Synergy': 'SynergyPlayTypes'}


def resolve_class(tid, rec, lib_eps):
    """Endpoint class for a test id: explicit field, else longest library class name that prefixes the id."""
    if rec.get('endpoint_class'):
        return rec['endpoint_class']
    t = re.sub(r'^(HG|XG|H|X|Y|live)_', '', tid)
    t = ALIASES.get(t.split('_')[0], t)
    best = max((c for c in lib_eps if t.startswith(c)), key=len, default=None)
    return best or t.split('_')[0]


def load_columns(discovery_dir, lib_eps):
    """test_id -> (endpoint_class, set(columns)) from every results_*.jsonl (successful tests only)."""
    recs = {}
    for f in sorted(glob.glob(os.path.join(discovery_dir, 'results_*.jsonl'))):
        for line in open(f):
            r = json.loads(line)
            recs.setdefault(r['id'], []).append(r)
    out = {}
    for tid, lst in recs.items():
        ok = [r for r in lst if r.get('ok')]
        if not ok:
            continue
        r = ok[-1]
        cols = set()
        for s in r.get('sets', {}).values():
            for c in s['columns']:
                m = re.match(r"^\('(.*)', '(.*)'\)$", c)
                cols.add((m.group(1) + ':' + m.group(2)) if (m and m.group(1)) else (m.group(2) if m else c))
        for k in r.get('live_keys', {}) or {}:
            cols.add(k)
        out[tid] = (resolve_class(tid, r, lib_eps), cols)
    return out


def find_cols(testcols, ep, var):
    cols = set(); hit = False
    for tid, (cls, cs) in testcols.items():
        if cls != ep:
            continue
        if var and var not in tid:
            continue
        hit = True; cols |= cs
    return hit, cols


def run(features, discovery_dir, qc_path=None):
    errors, warnings, info = [], [], {}
    ids = {f['id'] for f in features}
    byid = {f['id']: f for f in features}
    sigs = json.load(open(os.path.join(discovery_dir, 'library_signatures.json')))
    lib_eps = set(sigs)
    testcols = load_columns(discovery_dir, lib_eps)

    # 1. required fields
    for f in features:
        for k in REQUIRED:
            if not str(f.get(k, '')).strip():
                errors.append(f'{f["id"]}: empty required field {k}')
        if f['classification'] in ('CALCULATED', 'ENGINEERED') and not f['dependencies'] and not f['source_columns']:
            errors.append(f'{f["id"]}: {f["classification"]} but no source columns or dependencies')
        if f['classification'] == 'RAW' and not f['source_columns']:
            errors.append(f'{f["id"]}: RAW without source columns')

    # 2. dependencies exist, no cycles
    for f in features:
        for d in f['dependencies'] + f.get('optional_dependencies', []):
            if d not in ids:
                errors.append(f'{f["id"]}: dependency {d} not in registry')
    color = {}
    def dfs(n, stack):
        color[n] = 1
        for d in byid[n]['dependencies'] + byid[n].get('optional_dependencies', []):
            if d not in byid:
                continue
            if color.get(d) == 1:
                errors.append('dependency cycle: ' + ' -> '.join(stack + [n, d]))
            elif d not in color:
                dfs(d, stack + [n])
        color[n] = 2
    for n in byid:
        if n not in color:
            dfs(n, [])

    # 3. every source column maps to a real, observed column
    unmapped = []
    for f in features:
        for sc in f['source_columns']:
            m = SRC_RE.match(sc)
            if not m:
                errors.append(f'{f["id"]}: malformed source column "{sc}"'); continue
            ep, var, col = m.group('ep'), m.group('var'), m.group('col')
            if ep not in lib_eps and ep not in ('Odds',):
                errors.append(f'{f["id"]}: endpoint {ep} not in nba_api library signatures'); continue
            hit, cols = find_cols(testcols, ep, var)
            if not hit:
                warnings.append(f'{f["id"]}: endpoint {ep}{"["+var+"]" if var else ""} was never successfully tested; column {col} unconfirmed')
                unmapped.append((f['id'], sc)); continue
            if col not in cols:
                errors.append(f'{f["id"]}: column "{col}" not found in any tested response of {ep}{"["+var+"]" if var else ""}')
        for se in f['source_endpoints']:
            base = re.sub(r'\[.*\]', '', se).replace(' (nba_api.live)', '').strip()
            if base not in lib_eps and base not in ('n/a', 'Odds'):
                errors.append(f'{f["id"]}: source endpoint "{base}" not a library endpoint')
    info['unconfirmed_source_columns'] = unmapped

    # 4. temporal / leakage consistency
    def reaches_label(n, seen=None, through_lag=False):
        seen = seen or set()
        for d in byid[n]['dependencies'] + byid[n].get('optional_dependencies', []):
            if d in seen or d not in byid:
                continue
            seen.add(d)
            t = byid[d]['temporal_status']
            if t == 'label' and not through_lag:
                return True
            if reaches_label(d, seen, through_lag or t == 'lagged_observed'):
                return True
        return False
    for f in features:
        t = f['temporal_status']; pre = f['pregame_availability']
        if t == 'label' and not pre.startswith('No'):
            errors.append(f'{f["id"]}: label must be "No" pregame')
        if pre.startswith('No') and t not in ('label', 'lagged_observed'):
            errors.append(f'{f["id"]}: pregame "No" but temporal_status {t}')
        if pre.startswith('No') and f['leakage_risk'] == 'Low':
            errors.append(f'{f["id"]}: postgame quantity with Low leakage rating')
        if t in ('projected', 'pregame_known') and reaches_label(f['id']):
            errors.append(f'{f["id"]}: {t} feature reaches a label without passing through a lagged_observed feature')
        if t == 'projected' and not f['dependencies']:
            errors.append(f'{f["id"]}: projected feature with no dependencies')
        if t == 'external_pregame' and f['classification'] != 'EXTERNAL':
            errors.append(f'{f["id"]}: external_pregame must be EXTERNAL')
        if f['classification'] == 'EXTERNAL' and not (f['source_endpoints'] == ['n/a'] or any(d.startswith('EXT_') for d in f['dependencies']) or f['id'].startswith(('CTX_TRAVEL', 'BLO_SPREAD_HIST'))):
            warnings.append(f'{f["id"]}: EXTERNAL without an EXT_ dependency or n/a source')
        if f['classification'] == 'ENGINEERED' and t == 'lagged_observed' and f['leakage_risk'] == 'High':
            errors.append(f'{f["id"]}: ENGINEERED lagged feature rated High leakage')
        if f['classification'] in ('UNVERIFIED',) and f['validation_status'] not in ('unverified_source',):
            errors.append(f'{f["id"]}: UNVERIFIED classification needs validation_status unverified_source')
        if f['validation_status'] == 'external_unobtained' and f['classification'] != 'EXTERNAL':
            errors.append(f'{f["id"]}: external_unobtained but classification {f["classification"]}')

    # 5. formula_verified claims must be backed by qc results
    if qc_path and os.path.exists(qc_path):
        qc = json.load(open(qc_path))
        for f in features:
            if f['validation_status'] == 'formula_verified':
                if f['id'] not in QC_BACKING:
                    errors.append(f'{f["id"]}: marked formula_verified but has no QC backing entry')
                    continue
                for key, fld, thr, mode in QC_BACKING[f['id']]:
                    v = qc[key] if fld is None else qc[key][fld]
                    if (mode == 'min' and v < thr) or (mode in ('max', 'scalar_max') and v > thr):
                        errors.append(f'{f["id"]}: QC {key}.{fld}={v} fails {mode} {thr}')
        info['qc_backed_features'] = sorted(k for k in QC_BACKING)
    else:
        warnings.append('qc_results.json missing - formula_verified claims not checked')

    # 6. duplicated / highly collinear candidates (declared clusters)
    cl = defaultdict(list)
    for f in features:
        cl[f['correlation_cluster']].append(f['id'])
    info['correlation_clusters'] = {k: v for k, v in cl.items() if len(v) > 1}

    # 7. P0 hygiene
    info['p0_blocked_by_external'] = sorted(f['id'] for f in features if f['priority'] == 'P0' and f['classification'] in ('EXTERNAL', 'UNVERIFIED'))
    for f in features:
        if f['priority'] == 'P0' and f['classification'] == 'UNVERIFIED':
            errors.append(f'{f["id"]}: UNVERIFIED feature cannot be P0')
        # every projected P0 needs a transitive path to raw data from nba_api only or external-blocked
    # 8. every feature used by a market relevance is reachable; every ID referenced in P0 dependency chain is in P0 or P1
    for f in features:
        if f['priority'] == 'P0':
            for d in f['dependencies']:
                if d in byid and byid[d]['priority'] not in ('P0',) and byid[d]['temporal_status'] != 'label':
                    warnings.append(f'{f["id"]} (P0) depends on {d} ({byid[d]["priority"]})')
    return dict(errors=errors, warnings=warnings, info=info)
