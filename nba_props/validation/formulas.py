"""Identity checks of registry formulas against API-provided columns, on warehouse tables.

Correlation is NOT used to establish equality. Each check reports n, MAE, RMSE, signed bias, max |error|, p99 |error|, the share
within a per-row tolerance derived from the API's own rounding, and the list of exceptions. Verdicts:
  exact_within_rounding       every row within tolerance
  exact_with_exceptions       >= 99.95% of rows within tolerance; exceptions listed (cross-endpoint inconsistencies)
  approximate                 same quantity but inputs differ (e.g. tracking vs box possessions); mean |err| <= approx_tol; NOT an identity
  not_equal                   otherwise
UNITS: team_game.min comes from LeagueGameLog (240 per regulation game); team_advanced_game.min comes from TeamGameLogs (48).
Player minutes: player_game.min is integer-rounded; min_exact (from MIN_SEC) is used for rates.
"""
import numpy as np

PB = "FROM player_game p JOIN player_advanced_game a USING(game_id, player_id)"
TJ = "JOIN team_game t ON t.game_id = p.game_id AND t.team_id = p.team_id"
OJ = "JOIN team_game o ON o.game_id = p.game_id AND o.team_id <> p.team_id"
SEL = "p.game_id gid, p.player_id pid,"

CHECKS = {
    'ts_pct': dict(sa='p', sql=f"SELECT {SEL} p.pts / (2*(p.fga + 0.44*p.fta)) calc, a.ts_pct api, 0.0006 bound {PB} WHERE p.fga + 0.44*p.fta > 0 AND a.ts_pct IS NOT NULL", approx=0.002,
                   note='fraction; API rounds to 3 decimals'),
    'usg_pct': dict(sa='p', sql=f"SELECT {SEL} ((p.fga + 0.44*p.fta + p.tov) * (t.min/5)) / (p.min_exact * (t.fga + 0.44*t.fta + t.tov)) calc, a.usg_pct api, 0.0006 bound {PB} {TJ} WHERE p.min_exact >= 10 AND a.usg_pct IS NOT NULL", approx=0.02,
                    note='fraction; (team MIN)/5 = 48 in regulation'),
    'ast_pct': dict(sa='p', sql=f"SELECT {SEL} p.ast / ((p.min_exact / (t.min/5)) * t.fgm - p.fgm) calc, a.ast_pct api, 0.0006 bound {PB} {TJ} WHERE p.min_exact >= 10 AND a.ast_pct IS NOT NULL AND (p.min_exact / (t.min/5)) * t.fgm - p.fgm > 0", approx=0.03, note='fraction'),
    'reb_pct': dict(sa='p', sql=f"SELECT {SEL} p.reb * (t.min/5) / (p.min_exact * (t.reb + o.reb)) calc, a.reb_pct api, 0.0006 bound {PB} {TJ} {OJ} WHERE p.min_exact >= 10 AND a.reb_pct IS NOT NULL", approx=0.03, note='fraction'),
    'oreb_pct': dict(sa='p', sql=f"SELECT {SEL} p.oreb * (t.min/5) / (p.min_exact * (t.oreb + o.dreb)) calc, a.oreb_pct api, 0.0006 bound {PB} {TJ} {OJ} WHERE p.min_exact >= 10 AND a.oreb_pct IS NOT NULL", approx=0.03, note='fraction'),
    'dreb_pct': dict(sa='p', sql=f"SELECT {SEL} p.dreb * (t.min/5) / (p.min_exact * (t.dreb + o.oreb)) calc, a.dreb_pct api, 0.0006 bound {PB} {TJ} {OJ} WHERE p.min_exact >= 10 AND a.dreb_pct IS NOT NULL", approx=0.03, note='fraction'),
    'tm_tov_pct_api_definition': dict(sa='p', sql=f"SELECT {SEL} 100*p.tov / (p.fga + 0.44*p.fta + p.ast + p.tov) calc, a.tm_tov_pct api, 0.06 bound {PB} WHERE p.min >= 10 AND a.tm_tov_pct IS NOT NULL AND p.fga + 0.44*p.fta + p.ast + p.tov > 0", approx=0.5,
                                      note='percent 0-100. This is the API TM_TOV_PCT definition; it is NOT the registry TOV_RATE (turnovers per 100 possessions)'),
    'tov_pct_plain_vs_api': dict(sa='p', sql=f"SELECT {SEL} 100*p.tov / (p.fga + 0.44*p.fta + p.tov) calc, a.tm_tov_pct api, 0.06 bound {PB} WHERE p.min >= 10 AND a.tm_tov_pct IS NOT NULL AND p.fga + 0.44*p.fta + p.tov > 0", approx=0.5,
                                 note='NEGATIVE CONTROL: the same ratio without assists must not match'),
    'team_pace_from_api_poss': dict(sa='t', sql="SELECT a.game_id gid, a.team_id pid, 48 * a.poss / a.min calc, a.pace api, 0.5*48/a.min + 0.011 bound FROM team_advanced_game a JOIN team_game t USING(game_id, team_id) WHERE a.pace IS NOT NULL AND a.poss IS NOT NULL", approx=0.6,
                                    note='per-row bound 0.5*48/MIN: POSS is integer-rounded (overtime shrinks the bound)'),
    'team_poss_oliver_vs_api': dict(sa='t', sql="""SELECT t.game_id gid, t.team_id pid, 0.5*((t.fga + 0.4*t.fta - 1.07*(t.oreb/(t.oreb+o.dreb))*(t.fga-t.fgm) + t.tov) + (o.fga + 0.4*o.fta - 1.07*(o.oreb/(o.oreb+t.dreb))*(o.fga-o.fgm) + o.tov)) calc, a.poss api, 1.0 bound
                                    FROM team_game t JOIN team_game o ON o.game_id=t.game_id AND o.team_id<>t.team_id JOIN team_advanced_game a ON a.game_id=t.game_id AND a.team_id=t.team_id WHERE a.poss IS NOT NULL""", approx=2.0,
                                    note='possessions; API uses tracking/PBP possessions so the box formula is an ESTIMATE'),
    'team_poss_simple_vs_api': dict(sa='t', sql="SELECT t.game_id gid, t.team_id pid, t.fga + 0.44*t.fta - t.oreb + t.tov calc, a.poss api, 1.0 bound FROM team_game t JOIN team_advanced_game a ON a.game_id=t.game_id AND a.team_id=t.team_id WHERE a.poss IS NOT NULL", approx=3.0, note='possessions'),
    'player_poss_vs_oncourt_pace': dict(sa='p', sql=f"SELECT {SEL} a.pace * p.min_exact / 48 calc, a.poss api, 0.5 + 0.01 bound {PB} WHERE p.min_exact >= 5 AND a.pace IS NOT NULL AND a.poss IS NOT NULL", approx=1.5, note='possessions; integer-rounded POSS'),
    'min_vs_min_sec': dict(sa='player_game', sql="SELECT game_id gid, player_id pid, min calc, CAST(split_part(min_sec,':',1) AS DOUBLE) + CAST(split_part(min_sec,':',2) AS DOUBLE)/60 api, 0.5 + 0.0085 bound FROM player_game WHERE min_sec LIKE '%:%'", approx=0.5,
                           note='LeagueGameLog MIN is rounded to the nearest whole minute'),
    'rebound_supply_fit': dict(sa='t', sql="""SELECT t.game_id gid, t.team_id pid, 0.873*((t.fga-t.fgm)+(o.fga-o.fgm)) + 0.075*(t.fta+o.fta) + 1.70 calc, (t.reb + o.reb) api, 0.0 bound FROM team_game t JOIN team_game o ON o.game_id=t.game_id AND o.team_id<>t.team_id""", approx=6.0,
                               note='STATISTICAL RELATION, not an identity: coefficients were fitted on 2025-26 only, so other seasons are out-of-sample'),
}
COMPLETED = ('2023-24', '2024-25', '2025-26')


def _stats(df, approx):
    e = (df['calc'].astype(float) - df['api'].astype(float)).to_numpy()
    ok = np.isfinite(e)
    df, e = df[ok], e[ok]
    if len(e) == 0:
        return dict(n=0, verdict='no_data')
    a = np.abs(e)
    exceed = a - df['bound'].astype(float).to_numpy()
    within = exceed <= 1e-9
    share = float(within.mean())
    verdict = ('exact_within_rounding' if within.all() else 'exact_with_exceptions' if share >= 0.9995 else
               'approximate' if a.mean() <= approx else 'not_equal')
    bad = df[~within].assign(err=e[~within]).sort_values('err', key=abs, ascending=False).head(20)
    return dict(n=int(len(e)), mae=float(a.mean()), rmse=float(np.sqrt((e ** 2).mean())), bias=float(e.mean()), max_abs=float(a.max()),
                p99_abs=float(np.quantile(a, .99)), within_tol_share=share, n_exceptions=int((~within).sum()),
                exceptions=[[str(r.gid), str(r.pid), round(float(r.err), 4)] for r in bad.itertuples()], approx_tol=approx, verdict=verdict)


def run(con, seasons=COMPLETED):
    out = {}
    inlist = ','.join(f"'{s}'" for s in seasons)
    for name, c in CHECKS.items():
        sql = c['sql'].replace(' WHERE ', f" WHERE {c['sa']}.season IN ({inlist}) AND ", 1)
        r = _stats(con.execute(sql).df(), c['approx'])
        r['note'] = c['note']; r['seasons'] = list(seasons)
        out[name] = r
    return out


def reconcile_player_vs_team(con, seasons=COMPLETED):
    """Player sums vs team totals. Expected exceptions: team turnovers are credited to the team (player sum <= team)."""
    cols = ['pts', 'fgm', 'fga', 'fg3m', 'fg3a', 'ftm', 'fta', 'oreb', 'dreb', 'reb', 'ast', 'stl', 'blk', 'tov', 'pf']
    sel = ', '.join(f'sum(p.{c}) p_{c}, any_value(t.{c}) t_{c}' for c in cols)
    inlist = ','.join(f"'{s}'" for s in seasons)
    df = con.execute(f"SELECT p.game_id, p.team_id, {sel} FROM player_game p JOIN team_game t ON t.game_id=p.game_id AND t.team_id=p.team_id WHERE p.season IN ({inlist}) GROUP BY p.game_id, p.team_id").df()
    res = {'team_games': int(len(df)), 'seasons': list(seasons)}
    for c in cols:
        d = df[f'p_{c}'] - df[f't_{c}']
        res[c] = dict(exact_share=float((d == 0).mean()), player_gt_team=int((d > 0).sum()), player_lt_team=int((d < 0).sum()), max_abs=float(d.abs().max()))
    return res
