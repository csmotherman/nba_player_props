"""Executable quality-control checks on the feature registry.

run(features, discovery_dir) -> dict(errors=[...], warnings=[...], info={...})
Build refuses to write artifacts if errors is non-empty.
"""
import json, re, os, glob
from collections import defaultdict, Counter

SRC_RE = re.compile(r'^(?P<ep>[A-Za-z0-9]+)(?:\[(?P<var>[^\]]+)\])?\.(?P<col>.+)$')
REQUIRED = ['id', 'name', 'domain', 'description', 'classification', 'temporal_status', 'formula', 'aggregation_level',
            'historical_availability', 'pregame_availability', 'leakage_risk', 'leakage_notes', 'missing_data_handling',
            'validation_method', 'priority', 'validation_status']

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


def label_leaks(byid, start):
    """Return a path start -> ... -> label that does NOT pass through a lagged_observed node, or None.

    Path-state-aware: a node reached through a lagged node is a LEGITIMATE use of past outcomes, so traversal never expands
    lagged_observed nodes. A label reachable by ANY remaining path is a leak, even when the same label is also reachable
    legitimately (the old shared-visited-set implementation missed that case). Optional dependencies count. Cycles terminate.
    """
    seen, stack = set(), [(start, [start])]
    while stack:
        n, path = stack.pop()
        for d in byid[n]['dependencies'] + byid[n].get('optional_dependencies', []):
            if d not in byid:
                continue
            t = byid[d]['temporal_status']
            if t == 'label':
                return path + [d]
            if t == 'lagged_observed' or d in seen:
                continue            # past outcomes are fine here; do not expand
            seen.add(d)
            stack.append((d, path + [d]))
    return None


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
    for f in features:
        t = f['temporal_status']; pre = f['pregame_availability']
        if t == 'label' and not pre.startswith('No'):
            errors.append(f'{f["id"]}: label must be "No" pregame')
        if pre.startswith('No') and t not in ('label', 'lagged_observed'):
            errors.append(f'{f["id"]}: pregame "No" but temporal_status {t}')
        if pre.startswith('No') and f['leakage_risk'] == 'Low':
            errors.append(f'{f["id"]}: postgame quantity with Low leakage rating')
        if t in ('projected', 'pregame_known', 'external_pregame', 'unverified'):
            leak = label_leaks(byid, f['id'])
            if leak:
                errors.append(f'{f["id"]}: {t} feature reaches a label without passing through a lagged_observed feature: ' + ' -> '.join(leak))
        if t == 'lagged_observed':
            bad = [d for d in f['dependencies'] if d in byid and byid[d]['temporal_status'] in ('projected', 'external_pregame')]
            if bad:
                errors.append(f'{f["id"]}: lagged_observed feature depends on projected/external inputs {bad} (observation would embed a forecast)')
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

    # 5. verification claims must match the recorded evidence (no correlation-based or mismatched claims)
    ev = {}
    evp = os.path.join(discovery_dir, 'formula_checks.json')
    if os.path.exists(evp):
        ev = json.load(open(evp)).get('identities', {})
    from . import verification as V
    for fid, chk in V.IDENTITY.items():
        if fid in byid and chk not in ev:
            errors.append(f'{fid}: identity evidence "{chk}" missing from formula_checks.json')
    for f in features:
        vs = f['validation_status']
        if vs == 'identity_verified' and not str(f.get('verification', {}).get('identity', '')).startswith(('exact_within_rounding', 'exact_with_exceptions')):
            errors.append(f'{f["id"]}: identity_verified without exact evidence')
        if vs == 'identity_approximate' and f['id'] not in V.IDENTITY:
            errors.append(f'{f["id"]}: identity_approximate without an evidence check')
        if f['id'] in V.RELATED_ONLY and vs in ('identity_verified', 'identity_approximate'):
            errors.append(f'{f["id"]}: claims identity status but only has evidence for a different quantity')
        if vs == 'implemented_pit_verified' and f.get('implementation_status') == 'specified_only':
            errors.append(f'{f["id"]}: implemented_pit_verified but no implementation')
    info['identity_evidence'] = {k: v['verdict'] for k, v in ev.items()}

    # 5b. readiness / fallback integrity (priority, readiness and implementation are separate dimensions)
    for f in features:
        if f.get('optional_unavailable_without_fallback'):
            errors.append(f'{f["id"]}: optional dependency unavailable with no declared fallback: {f["optional_unavailable_without_fallback"]}')
        if f.get('fallback_for') and not f.get('fallback'):
            errors.append(f'{f["id"]}: fallback_for without fallback text')
        if f['priority'] == 'P0' and f.get('readiness', '').startswith('BLOCKED') and f['classification'] not in ('EXTERNAL',):
            errors.append(f'{f["id"]}: P0 feature blocked by {f["blocking_inputs"]} but is not itself an external source')
    info['readiness_counts'] = dict(Counter(f.get('readiness') for f in features))

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
