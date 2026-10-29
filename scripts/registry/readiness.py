"""Transitive execution-readiness analysis.

Readiness = can this feature be COMPUTED from available data today, honouring only declared NBA-only fallbacks.
It is independent of PRIORITY (importance) and of IMPLEMENTATION status (code exists and is tested).

Rules
 * REQUIRED dependency unavailable            -> BLOCKED, unless the feature declares a fallback for that dependency -> DEGRADED
 * OPTIONAL dependency unavailable            -> never blocks; recorded in optional_unavailable; a declared fallback is mandatory (checked)
 * Own EXTERNAL / UNVERIFIED input            -> BLOCKED unless a 'SELF' fallback is declared -> DEGRADED
 * DEGRADED propagates through required dependants (they run, on degraded inputs)
"""
from .fallbacks import FALLBACKS

OK, DEGRADED, BLOCKED_UNVERIFIED, BLOCKED_EXTERNAL = 0, 1, 2, 3
NAMES = {OK: 'EXECUTABLE_NBA_ONLY', DEGRADED: 'EXECUTABLE_DEGRADED', BLOCKED_UNVERIFIED: 'BLOCKED_UNVERIFIED', BLOCKED_EXTERNAL: 'BLOCKED_EXTERNAL'}


def compute(features, fallbacks=FALLBACKS):
    byid = {f['id']: f for f in features}
    memo = {}

    def go(i):
        if i in memo:
            return memo[i]
        f = byid[i]
        fb = set(fallbacks.get(i, {}).get('for_', []))
        st, blockers, used = OK, set(), []
        own = {'EXTERNAL': BLOCKED_EXTERNAL, 'UNVERIFIED': BLOCKED_UNVERIFIED}.get(f['classification'], OK)
        if own:
            if 'SELF' in fb:
                st = max(st, DEGRADED); used.append(f'{i}:SELF')
            else:
                st = max(st, own); blockers.add(i)
        for d in f['dependencies']:
            ds, db, du, _ = go(d)
            used += du
            if ds >= BLOCKED_UNVERIFIED and d in fb:
                st = max(st, DEGRADED); used.append(f'{i}:{d}')
            else:
                st = max(st, ds); blockers |= db
        opt_unavail = []
        for d in f['optional_dependencies']:
            ds, _, _, _ = go(d)
            if ds >= BLOCKED_UNVERIFIED:
                opt_unavail.append(d)
        memo[i] = (st, blockers, used, opt_unavail)
        return memo[i]

    out = {}
    for i in byid:
        st, blockers, used, opt = go(i)
        kind = ''
        if st >= BLOCKED_UNVERIFIED:
            kind = NAMES[max(byid[b]['classification'] == 'EXTERNAL' and BLOCKED_EXTERNAL or BLOCKED_UNVERIFIED for b in blockers)]
        out[i] = dict(readiness=kind or NAMES[st], blocking_inputs=sorted(blockers), fallbacks_used=sorted(set(used)),
                      optional_unavailable=sorted(opt),
                      optional_unavailable_without_fallback=sorted(d for d in opt if d not in fallbacks.get(i, {}).get('for_', [])))
    return out
