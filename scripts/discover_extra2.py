"""Third-round discovery: opponent shot locations, library pace_adjust, period splits."""
import sys, json, time, os
import nba_api.stats.endpoints as E
OUT = sys.argv[1]; os.makedirs(f'{OUT}/frames', exist_ok=True)
S = '2025-26'; out = open(f'{OUT}/results_extra2.jsonl', 'w')
def t(i, fn):
    r = {'id': i, 'ok': False}; t0 = time.time()
    for a in range(3):
        try:
            x = fn(); dfs = x.get_data_frames(); names = list(x.expected_data.keys()) if len(x.expected_data) == len(dfs) else [f'set{j}' for j in range(len(dfs))]
            r['sets'] = {n: {'rows': len(d), 'columns': [str(c) for c in d.columns]} for n, d in zip(names, dfs)}
            for n, d in zip(names, dfs):
                if len(d): d.to_csv(f'{OUT}/frames/{i}__{n}.csv', index=False)
            r['ok'] = True; r['nonempty'] = any(len(d) for d in dfs); break
        except Exception as e:
            r['error'] = f'{type(e).__name__}: {str(e)[:200]}'; time.sleep(4)
    r['elapsed_s'] = round(time.time() - t0, 1); out.write(json.dumps(r) + '\n'); out.flush(); print(i, r['ok'], r.get('nonempty'), r.get('error', ''), flush=True)
t('Y_LeagueDashTeamShotLocations_Opponent', lambda: E.LeagueDashTeamShotLocations(season=S, measure_type_simple='Opponent', timeout=60))
t('Y_LeagueDashPlayerStats_PaceAdjustY', lambda: E.LeagueDashPlayerStats(season=S, pace_adjust='Y', per_mode_detailed='Totals', timeout=60))
t('Y_LeagueDashPlayerStats_Q4', lambda: E.LeagueDashPlayerStats(season=S, period=4, per_mode_detailed='Totals', timeout=60))
t('Y_LeagueDashPlayerStats_PerPoss', lambda: E.LeagueDashPlayerStats(season=S, per_mode_detailed='Per100Possessions', timeout=60))
t('Y_LeagueDashPlayerStats_Last10_adv', lambda: E.LeagueDashPlayerStats(season=S, last_n_games=10, measure_type_detailed_defense='Advanced', per_mode_detailed='Totals', timeout=60))
t('Y_LeagueDashTeamStats_Opp_Q4', lambda: E.LeagueDashTeamStats(season=S, period=4, measure_type_detailed_defense='Opponent', per_mode_detailed='Totals', timeout=60))
t('Y_TeamDashLineups_OnCourt', lambda: E.TeamDashLineups(team_id=1610612743, season=S, group_quantity=5, measure_type_detailed_defense='Advanced', timeout=60))
t('Y_LeagueDashTeamClutch', lambda: E.LeagueDashTeamClutch(season=S, timeout=60))
print('DONE')
