"""Quality-control checks that back claims made in the blueprint. Writes data/discovery/qc_results.json.

Usage: python qc_checks.py <frames_dir> <out_json>
  frames_dir: directory of CSVs written by discover_endpoints.py (needs the 2025-26 main-phase frames)
Network is used only for the single-day tracking window test and the starter-flag test.
"""
import sys, json, random, time
import numpy as np, pandas as pd
import nba_api.stats.endpoints as E

FR, OUT = sys.argv[1] + '/', sys.argv[2]
rd = lambda f: pd.read_csv(FR + f, dtype={'GAME_ID': str, 'gameId': str})
res = {}

# --- 1. season-type contamination of PlayerGameLogs
a = rd('PlayerGameLogs_Advanced__PlayerGameLogs.csv'); lg = rd('LeagueGameLog_P__LeagueGameLog.csv')
res['playergamelogs_game_id_prefix_counts'] = a.GAME_ID.str[:3].value_counts().to_dict()
res['leaguegamelog_game_id_prefix_counts'] = lg.GAME_ID.str[:3].value_counts().to_dict()
res['leaguegamelog_rows_min_zero'] = int((lg.MIN == 0).sum())
res['rows_per_team_game_mean'] = float(lg.groupby(['GAME_ID', 'TEAM_ID']).size().mean())

# --- 2. formula reproduction vs API-provided columns (regular season, MIN>=10)
ar = a[a.GAME_ID.str[:3] == '002'].drop(columns=['FGA', 'FGM', 'FG_PCT'], errors='ignore')
pb = rd('PlayerGameLogs_Base__PlayerGameLogs.csv'); pb = pb[pb.GAME_ID.str[:3] == '002']
tl = rd('TeamGameLogs_Base__TeamGameLogs.csv'); tl = tl[tl.GAME_ID.str[:3] == '002']
ta = rd('TeamGameLogs_Advanced__TeamGameLogs.csv'); ta = ta[ta.GAME_ID.str[:3] == '002']
res['team_min_col_regulation_value'] = float(tl.MIN.mode()[0])
t = tl.merge(ta[['GAME_ID', 'TEAM_ID', 'POSS', 'PACE']], on=['GAME_ID', 'TEAM_ID'])
o = tl[['GAME_ID', 'TEAM_ID', 'FGA', 'FTA', 'OREB', 'DREB', 'TOV', 'FGM']].rename(columns=lambda c: c if c == 'GAME_ID' else 'o_' + c)
t = t.merge(o, on='GAME_ID'); t = t[t.TEAM_ID != t.o_TEAM_ID]
t['poss_simple'] = t.FGA + 0.44 * t.FTA - t.OREB + t.TOV
side = lambda fga, fta, orb, drb_o, fgm, tov: fga + 0.4 * fta - 1.07 * (orb / (orb + drb_o)) * (fga - fgm) + tov
t['poss_oliver'] = 0.5 * (side(t.FGA, t.FTA, t.OREB, t.o_DREB, t.FGM, t.TOV) + side(t.o_FGA, t.o_FTA, t.o_OREB, t.DREB, t.o_FGM, t.o_TOV))
t['pace_calc'] = 48 * t.poss_oliver / t.MIN
res['team_poss_simple_vs_api'] = {'mae': float((t.POSS - t.poss_simple).abs().mean()), 'corr': float(np.corrcoef(t.POSS, t.poss_simple)[0, 1])}
res['team_poss_oliver_vs_api'] = {'mae': float((t.POSS - t.poss_oliver).abs().mean()), 'corr': float(np.corrcoef(t.POSS, t.poss_oliver)[0, 1])}
res['team_pace_48poss_over_min_vs_api_pace_using_api_poss'] = float((t.PACE - 48 * t.POSS / t.MIN).abs().mean())
res['team_poss_is_integer_share'] = float((t.POSS == t.POSS.round()).mean())

x = pb.merge(ar[['GAME_ID', 'PLAYER_ID', 'USG_PCT', 'AST_PCT', 'REB_PCT', 'OREB_PCT', 'DREB_PCT', 'TM_TOV_PCT', 'POSS', 'PACE', 'TS_PCT']], on=['GAME_ID', 'PLAYER_ID'])
x = x.merge(tl[['GAME_ID', 'TEAM_ID', 'FGA', 'FTA', 'TOV', 'FGM', 'OREB', 'DREB', 'REB', 'MIN']].rename(columns=lambda c: c if c in ('GAME_ID', 'TEAM_ID') else 'T_' + c), on=['GAME_ID', 'TEAM_ID'])
op = tl[['GAME_ID', 'TEAM_ID', 'OREB', 'DREB']].rename(columns={'TEAM_ID': 'O_TEAM', 'OREB': 'O_OREB', 'DREB': 'O_DREB'})
x = x.merge(op, on='GAME_ID'); x = x[(x.TEAM_ID != x.O_TEAM) & (x.MIN >= 10)].copy()
cmp = lambda api, calc: {'mae': float((api - calc).abs().mean()), 'corr': float(np.corrcoef(api.fillna(0), calc.fillna(0))[0, 1]), 'n': int(len(api))}
x['usg'] = ((x.FGA + 0.44 * x.FTA + x.TOV) * x.T_MIN) / (x.MIN * (x.T_FGA + 0.44 * x.T_FTA + x.T_TOV))
res['usg_formula_vs_api_USG_PCT_fraction_scale'] = cmp(x.USG_PCT, x.usg)
x['astp'] = x.AST / ((x.MIN / x.T_MIN) * x.T_FGM - x.FGM); res['ast_pct_formula_vs_api'] = cmp(x.AST_PCT, x.astp)
x['rebp'] = x.REB * x.T_MIN / (x.MIN * (x.T_REB + x.O_OREB + x.O_DREB)); res['reb_pct_formula_vs_api'] = cmp(x.REB_PCT, x.rebp)
x['orebp'] = x.OREB * x.T_MIN / (x.MIN * (x.T_OREB + x.O_DREB)); res['oreb_pct_formula_vs_api'] = cmp(x.OREB_PCT, x.orebp)
x['drebp'] = x.DREB * x.T_MIN / (x.MIN * (x.T_DREB + x.O_OREB)); res['dreb_pct_formula_vs_api'] = cmp(x.DREB_PCT, x.drebp)
x['ts'] = x.PTS / (2 * (x.FGA + 0.44 * x.FTA)); res['ts_pct_formula_vs_api'] = cmp(x.TS_PCT, x.ts)
x['tov_a'] = 100 * x.TOV / (x.FGA + 0.44 * x.FTA + x.TOV); x['tov_b'] = 100 * x.TOV / (x.FGA + 0.44 * x.FTA + x.AST + x.TOV)
res['tm_tov_pct_vs_TOV_over_FGA_FTA_TOV_x100'] = cmp(x.TM_TOV_PCT, x.tov_a); res['tm_tov_pct_vs_TOV_over_FGA_FTA_AST_TOV_x100'] = cmp(x.TM_TOV_PCT, x.tov_b)
x['oc_poss'] = x.PACE * x.MIN / 48; res['player_poss_vs_onCourtPace_x_MIN_over_48'] = cmp(x.POSS, x.oc_poss)
x['sec'] = x.MIN_SEC.str.split(':').apply(lambda s: int(s[0]) + int(s[1]) / 60); res['min_vs_min_sec_max_abs_diff'] = float((x.MIN - x.sec).abs().max())


# --- 5. rebound-opportunity identity: total rebounds vs missed field goals (both teams)
tt = tl.merge(tl[['GAME_ID', 'TEAM_ID', 'FGA', 'FGM', 'FTA', 'REB']].rename(columns=lambda c: c if c == 'GAME_ID' else 'o_' + c), on='GAME_ID')
tt = tt[tt.TEAM_ID != tt.o_TEAM_ID]
tt['fg_miss_both'] = (tt.FGA - tt.FGM) + (tt.o_FGA - tt.o_FGM); tt['reb_both'] = tt.REB + tt.o_REB; tt['fta_both'] = tt.FTA + tt.o_FTA
res['rebound_identity'] = {'mean_total_rebounds': float(tt.reb_both.mean()), 'mean_fg_misses_both_teams': float(tt.fg_miss_both.mean()),
                           'ratio_reb_to_fg_misses': float((tt.reb_both / tt.fg_miss_both).mean()),
                           'corr_reb_vs_fgmiss': float(np.corrcoef(tt.reb_both, tt.fg_miss_both)[0, 1]),
                           'ols_reb_on_fgmiss_and_fta_coefs': [float(v) for v in np.linalg.lstsq(np.c_[tt.fg_miss_both, tt.fta_both, np.ones(len(tt))], tt.reb_both, rcond=None)[0]]}

# --- 6. schedule contents for the in-progress season
sc = pd.read_csv(FR + 'ScheduleLeagueV2_2026-27__SeasonGames.csv', dtype=str)
res['schedule_2026_27_game_id_prefix_counts'] = sc.gameId.str[:3].value_counts().to_dict()
res['schedule_2026_27_status_counts'] = sc.gameStatus.value_counts().to_dict()

# --- 3. single-day window reproduces game-level tracking (network)
D = '2026-01-15'
pt = E.LeagueDashPtStats(season='2025-26', pt_measure_type='Passing', player_or_team='Player', per_mode_simple='Totals', date_from_nullable=D, date_to_nullable=D, timeout=60).get_data_frames()[0]
g = pb.merge(lg[['GAME_ID', 'PLAYER_ID', 'GAME_DATE']], on=['GAME_ID', 'PLAYER_ID']) if 'GAME_DATE' not in pb.columns else pb
g = g[g.GAME_DATE.str[:10] == D]
j = pt.merge(g[['PLAYER_ID', 'AST']], on='PLAYER_ID', suffixes=('_pt', '_gl'))
res['single_day_passing_window'] = {'date': D, 'players': int(len(pt)), 'gp_max': int(pt.GP.max()), 'ast_match_rate_vs_gamelog': float((j.AST_pt == j.AST_gl).mean()), 'potential_ast_sum': int(pt.POTENTIAL_AST.sum())}

# --- 4. starter flag derivable from BoxScoreTraditionalV3.position?
games = sorted(tl.GAME_ID.unique()); random.seed(7); sample = random.sample(games, 20); ok = 0; counts = []
for gid in sample:
    for _ in range(3):
        try:
            p = E.BoxScoreTraditionalV3(game_id=gid, timeout=60).get_data_frames()[0]; break
        except Exception: time.sleep(3); p = None
    if p is None: continue
    c = p[p.position.notna() & (p.position != '')].groupby('teamId').size().tolist(); counts.append(c); ok += all(v == 5 for v in c) and len(c) == 2
res['starter_flag_position_nonnull_equals_5_per_team'] = {'games_tested': len(counts), 'games_exact_5_per_team': ok}
json.dump(res, open(OUT, 'w'), indent=1, default=float)
print(json.dumps(res, indent=1, default=float))
