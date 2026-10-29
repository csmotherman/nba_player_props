"""Feature registry source. Importing this package populates common.ALL."""
from . import common
from . import part1_box_minutes_shooting, part2_playmaking_rebounding_team, part3_projection_context  # noqa: F401


def load():
    return common.ALL


def finalize():
    """Apply the single P0 authority, then attach readiness, fallbacks, verification matrix and implementation status."""
    import sys
    from pathlib import Path
    root = str(Path(__file__).resolve().parent.parent.parent)
    if root not in sys.path:
        sys.path.insert(0, root)
    from nba_props.features.catalog import IMPLEMENTED, PARTIAL
    from . import readiness, verification
    from .fallbacks import FALLBACKS
    from .priorities import P0
    for f in common.ALL:
        f['priority'] = 'P0' if f['id'] in P0 else ('P1' if f['priority'] == 'P0' else f['priority'])
    missing = (P0 | set(FALLBACKS) | set(IMPLEMENTED)) - {f['id'] for f in common.ALL}
    assert not missing, f'ids referenced but not in registry: {sorted(missing)}'
    ready = readiness.compute(common.ALL)
    ev = verification.load_evidence()
    for f in common.ALL:
        f['declared_validation_status'] = f['validation_status']
        r = ready[f['id']]
        f.update(readiness=r['readiness'], blocking_inputs=r['blocking_inputs'], fallbacks_used=r['fallbacks_used'],
                 optional_unavailable=r['optional_unavailable'], optional_unavailable_without_fallback=r['optional_unavailable_without_fallback'],
                 fallback=FALLBACKS.get(f['id'], {}).get('text', ''), fallback_for=FALLBACKS.get(f['id'], {}).get('for_', []))
        f['verification'] = verification.matrix(f, IMPLEMENTED, ev)
        f['validation_status'] = verification.summary_status(f, f['verification'], IMPLEMENTED)
        f['implementation_status'] = ('implemented_partial' if f['id'] in PARTIAL else 'implemented') if f['id'] in IMPLEMENTED else 'specified_only'
        f['implemented_columns'] = IMPLEMENTED.get(f['id'], [])
        f['implementation_note'] = PARTIAL.get(f['id'], '')
    return common.ALL
