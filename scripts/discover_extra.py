"""Second-round discovery: V3 box score history, as-of date filters, in-progress season and pregame (unplayed game) availability."""
import sys, json, time, os
import nba_api.stats.endpoints as E
import nba_api.live.nba.endpoints as L
OUT = sys.argv[1]; os.makedirs(f'{OUT}/frames', exist_ok=True)
S = '2025-26'; PRE = '0022600144'   # unplayed game on discovery day (ATL vs CLE, 2026-10-29)
out = open(f'{OUT}/results_extra.jsonl', 'w')
def t(i, fn):
    r = {'id': i, 'ok': False}; t0 = time.time()
    for a in range(3):
        try:
            x = fn()
            if isinstance(x, dict):
                r['live_keys'] = list(x.keys()); r['sample'] = json.dumps(x)[:800]; r['ok'] = r['nonempty'] = True
            else:
                dfs = x.get_data_frames(); names = list(x.expected_data.keys()) if len(x.expected_data) == len(dfs) else [f'set{j}' for j in range(len(dfs))]
                r['sets'] = {n: {'rows': len(d), 'columns': [str(c) for c in d.columns]} for n, d in zip(names, dfs)}
                for n, d in zip(names, dfs):
                    if len(d): d.to_csv(f'{OUT}/frames/{i}__{n}.csv', index=False)
                r['ok'] = True; r['nonempty'] = any(len(d) for d in dfs)
            break
        except Exception as e:
            r['error'] = f'{type(e).__name__}: {str(e)[:200]}'; time.sleep(4)
    r['elapsed_s'] = round(time.time() - t0, 1); out.write(json.dumps(r) + '\n'); out.flush(); print(i, r['ok'], r.get('nonempty'), r.get('error', ''), flush=True)
for gid, tag in [('0029600001', '1996-97'), ('0020700001', '2007-08'), ('0021300001', '2013-14'), ('0021700001', '2017-18'), ('0021800001', '2018-19'), ('0021900001', '2019-20')]:
    for b in ['Traditional', 'Advanced', 'Usage', 'Scoring', 'Misc', 'FourFactors']:
        t(f'XG_BoxScore{b}V3_{tag}', lambda b=b, gid=gid: getattr(E, f'BoxScore{b}V3')(game_id=gid, timeout=60))
for gid, tag in [('0021700001', '2017-18'), ('0021800001', '2018-19')]:
    for c in ['BoxScoreMatchupsV3', 'BoxScoreDefensiveV2', 'BoxScoreHustleV2']:
        t(f'XG_{c}_{tag}', lambda c=c, gid=gid: getattr(E, c)(game_id=gid, timeout=60))
t('X_LeagueGameLog_P_2026-27', lambda: E.LeagueGameLog(season='2026-27', player_or_team_abbreviation='P', timeout=60))
t('X_PlayerGameLogs_2026-27_RS', lambda: E.PlayerGameLogs(season_nullable='2026-27', season_type_nullable='Regular Season', timeout=60))
t('X_PlayerGameLogs_2025-26_RS_dates', lambda: E.PlayerGameLogs(season_nullable=S, season_type_nullable='Regular Season', date_from_nullable='2026-01-01', date_to_nullable='2026-01-15', timeout=60))
t('X_LeagueDashPlayerStats_asof', lambda: E.LeagueDashPlayerStats(season=S, date_to_nullable='2026-01-01', per_mode_detailed='Totals', timeout=60))
t('X_LeagueDashPlayerStats_2026-27', lambda: E.LeagueDashPlayerStats(season='2026-27', per_mode_detailed='Totals', timeout=60))
t('X_LeagueDashPtStats_Pass_asof', lambda: E.LeagueDashPtStats(season=S, pt_measure_type='Passing', player_or_team='Player', per_mode_simple='Totals', date_to_nullable='2026-01-01', timeout=60))
t('X_LeagueDashPtStats_Reb_asof', lambda: E.LeagueDashPtStats(season=S, pt_measure_type='Rebounding', player_or_team='Player', per_mode_simple='Totals', date_to_nullable='2026-01-01', timeout=60))
t('X_TeamPlayerOnOffSummary_asof', lambda: E.TeamPlayerOnOffSummary(team_id=1610612743, season=S, date_to_nullable='2026-01-01', timeout=60))
t('X_LeagueDashLineups_asof', lambda: E.LeagueDashLineups(season=S, group_quantity=5, date_to_nullable='2026-01-01', timeout=60))
t('X_LeagueDashTeamStats_Adv_asof', lambda: E.LeagueDashTeamStats(season=S, measure_type_detailed_defense='Advanced', date_to_nullable='2026-01-01', timeout=60))
t('X_LeagueDashTeamStats_Adv_Last10', lambda: E.LeagueDashTeamStats(season=S, measure_type_detailed_defense='Advanced', last_n_games=10, timeout=60))
t('X_LeagueDashPlayerStats_vsPos_G', lambda: E.LeagueDashPlayerStats(season=S, player_position_abbreviation_nullable='G', per_mode_detailed='Totals', timeout=60))
t('X_LeagueDashPlayerStats_vsOpp', lambda: E.LeagueDashPlayerStats(season=S, opponent_team_id=1610612747, per_mode_detailed='Totals', timeout=60))
t('X_LeagueDashTeamStats_vsConf', lambda: E.LeagueDashTeamStats(season=S, measure_type_detailed_defense='Opponent', vs_conference_nullable='East', timeout=60))
t('X_PregameBoxSummaryV3', lambda: E.BoxScoreSummaryV3(game_id=PRE, timeout=60))
t('X_PregameBoxTraditionalV3', lambda: E.BoxScoreTraditionalV3(game_id=PRE, timeout=60))
t('X_PregamePlayByPlayV3', lambda: E.PlayByPlayV3(game_id=PRE, timeout=60))
t('X_Live_BoxScore_pregame', lambda: L.BoxScore(game_id=PRE, timeout=30).get_dict())
t('X_CommonTeamRoster_2026-27', lambda: E.CommonTeamRoster(team_id=1610612737, season='2026-27', timeout=60))
t('X_PlayerIndex_2026-27', lambda: E.PlayerIndex(season='2026-27', timeout=60))
t('X_TeamGameLogs_2026-27', lambda: E.TeamGameLogs(season_nullable='2026-27', season_type_nullable='Regular Season', timeout=60))
t('X_LeagueDashPtDefend_asof', lambda: E.LeagueDashPtDefend(season=S, defense_category='Overall', date_to_nullable='2026-01-01', timeout=60))
t('X_LeagueHustle_asof', lambda: E.LeagueHustleStatsPlayer(season=S, date_to_nullable='2026-01-01', timeout=60))
t('X_Synergy_Prior', lambda: E.SynergyPlayTypes(season='2024-25', play_type_nullable='Spotup', player_or_team_abbreviation='P', type_grouping_nullable='offensive', timeout=60))
print('DONE')
