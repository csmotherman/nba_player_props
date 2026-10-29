"""Feature registry source. Importing this package populates common.ALL."""
from . import common
from . import part1_box_minutes_shooting, part2_playmaking_rebounding_team, part3_projection_context  # noqa: F401


def load():
    return common.ALL


def finalize():
    """Apply the single P0 authority and return the registry."""
    from .priorities import P0
    for f in common.ALL:
        if f['priority'] == 'P0' and f['id'] not in P0:
            f['priority'] = 'P1'
        elif f['id'] in P0:
            f['priority'] = 'P0'
    missing = P0 - {f['id'] for f in common.ALL}
    assert not missing, f'P0 ids not in registry: {sorted(missing)}'
    return common.ALL
