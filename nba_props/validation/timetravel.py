"""Time-travel audit: features for a historical game must not change when LATER data is added or the target game itself is altered."""
import duckdb
import pandas as pd
from ..features import asof
from ..storage.db import DDL

RESULT_TABLES = {'player_game': 'game_date', 'team_game': 'game_date', 'player_advanced_game': None, 'team_advanced_game': None,
                 'historical_starters': None, 'historical_inactives': None}


def clone(src, up_to_date=None):
    """In-memory copy of the warehouse. Result tables are truncated to games dated <= up_to_date; the SCHEDULE (games) is kept whole
    because it is pregame-known. Returns a new connection."""
    mem = duckdb.connect(':memory:')
    mem.execute(DDL)
    for ddl in ("ALTER TABLE player_game ADD COLUMN IF NOT EXISTS min_exact DOUBLE", "ALTER TABLE player_game ADD COLUMN IF NOT EXISTS min_conflict BOOLEAN"):
        mem.execute(ddl)
    for t in ('games', 'teams', 'players', 'player_game', 'team_game', 'player_advanced_game', 'team_advanced_game', 'historical_starters', 'historical_inactives'):
        df = src.execute(f'SELECT * FROM {t}').df()
        if up_to_date is not None and t != 'games' and t in RESULT_TABLES:
            ids = src.execute('SELECT game_id FROM games WHERE game_date <= ?', [up_to_date]).df()
            df = df[df.game_id.isin(set(ids.game_id))]
        mem.register('_x', df)
        mem.execute(f'INSERT INTO {t} BY NAME SELECT * FROM _x')
        mem.unregister('_x')
    return mem


def snapshot_features(con, season, hours, game_date):
    asof.build(con, season, [hours])
    cols = [c[0] for c in con.execute('DESCRIBE asof_player_features').fetchall() if c[0] != 'limitations']
    q = f"SELECT {','.join(cols)} FROM asof_player_features WHERE season=? AND cutoff_hours=? AND game_date=? ORDER BY game_id, player_id"
    return con.execute(q, [season, float(hours), game_date]).df()


def compare(a, b, atol=1e-9):
    """Return (n_rows, [(column, n_mismatching_rows)]). NaN == NaN."""
    if list(a.columns) != list(b.columns) or len(a) != len(b):
        return len(a), [('shape/columns differ', max(len(a), len(b)))]
    bad = []
    for c in a.columns:
        x, y = a[c], b[c]
        if pd.api.types.is_numeric_dtype(x) and not pd.api.types.is_bool_dtype(x):
            neq = ~((x - y).abs() <= atol) & ~(x.isna() & y.isna())
        else:
            neq = ~((x == y) | (x.isna() & y.isna()))
        if neq.any():
            bad.append((c, int(neq.sum())))
    return len(a), bad


def time_travel(con, season, game_date, hours=6, later_until=None):
    """Features for target games on `game_date` computed (1) with data only up to game_date and (2) with ALL later data present.
    Returns dict(n_rows, mismatching_columns)."""
    early = clone(con, up_to_date=game_date)
    f1 = snapshot_features(early, season, hours, game_date)
    full = clone(con, up_to_date=later_until)
    f2 = snapshot_features(full, season, hours, game_date)
    n, bad = compare(f1, f2)
    early.close(); full.close()
    return dict(game_date=str(game_date), n_rows=n, mismatching_columns=bad)
