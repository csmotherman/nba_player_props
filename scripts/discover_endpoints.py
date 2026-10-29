"""Live endpoint discovery for nba_api.

Calls a curated list of endpoints with known-good sample IDs, records status, result-set names,
columns, row counts and elapsed time to a JSONL file (one line per test). Full frames are dumped as
CSV into <outdir>/frames/ so formulas can be QC'd against the API's own derived columns.

Usage: python discover_endpoints.py <outdir> [phase]    phase: main | history
"""
import sys, os, json, time, importlib, traceback
from concurrent.futures import ThreadPoolExecutor
import pandas as pd

OUT = sys.argv[1]; PHASE = sys.argv[2] if len(sys.argv) > 2 else 'main'
os.makedirs(f'{OUT}/frames', exist_ok=True)
import nba_api.stats.endpoints as E
import nba_api.live.nba.endpoints as L

S = '2025-26'
JOKIC, LEBRON, DEN = 203999, 2544, 1610612743

def get_cls(name):
    return getattr(E, name, None) or getattr(L, name)

def run(spec):
    tid, cls, kw = spec['id'], spec['cls'], spec.get('kw', {})
    rec = {'id': tid, 'endpoint_class': cls, 'params_used': {k: str(v) for k, v in kw.items()}, 'ok': False}
    t = time.time()
    for attempt in range(3):
        try:
            C = get_cls(cls)
            ep = C(**kw, timeout=45) if cls not in ('ScoreBoard', 'Odds', 'BoxScore', 'PlayByPlay') else C(**kw, timeout=45)
            dfs = ep.get_data_frames()
            names = list(getattr(ep, 'expected_data', {}).keys()) if hasattr(ep, 'expected_data') else []
            if len(names) != len(dfs):
                names = [f'set{i}' for i in range(len(dfs))]
            rec['sets'] = {}
            for n, d in zip(names, dfs):
                rec['sets'][n] = {'rows': int(len(d)), 'columns': [str(c) for c in d.columns]}
                if len(d): d.to_csv(f"{OUT}/frames/{tid}__{n}.csv", index=False)
            rec['ok'] = True; rec['nonempty'] = any(v['rows'] > 0 for v in rec['sets'].values())
            break
        except Exception as e:
            rec['error'] = f'{type(e).__name__}: {str(e)[:200]}'
            time.sleep(2 + attempt * 3)
    rec['elapsed_s'] = round(time.time() - t, 1)
    with open(f'{OUT}/results_{PHASE}.jsonl', 'a') as f: f.write(json.dumps(rec) + '\n')
    print(tid, rec['ok'], rec.get('nonempty'), rec.get('error', ''), flush=True)
    return rec

def main_specs():
    # bootstrap sample game ids
    gl = E.LeagueGameLog(season=S, player_or_team_abbreviation='T', timeout=60).get_data_frames()[0]
    den = gl[gl.TEAM_ID == DEN].sort_values('GAME_DATE')
    game = den.iloc[len(den) // 2].GAME_ID
    opp_abbr = [x for x in gl[gl.GAME_ID == game].TEAM_ABBREVIATION if x != 'DEN'][0]
    json.dump({'game_id': game, 'n_games_den': len(den), 'last_date': str(gl.GAME_DATE.max())}, open(f'{OUT}/bootstrap.json', 'w'))
    g = game
    sp = []
    def add(i, c, **kw): sp.append({'id': i, 'cls': c, 'kw': kw})
    # --- logs / finders
    add('LeagueGameLog_P', 'LeagueGameLog', season=S, player_or_team_abbreviation='P')
    add('LeagueGameLog_T', 'LeagueGameLog', season=S, player_or_team_abbreviation='T')
    for m in ['Base', 'Advanced', 'Misc', 'Scoring', 'Usage', 'Four Factors', 'Defense']:
        add(f'PlayerGameLogs_{m}', 'PlayerGameLogs', season_nullable=S, measure_type_player_game_logs_nullable=m)
    for m in ['Base', 'Advanced', 'Four Factors', 'Misc', 'Scoring', 'Opponent', 'Defense']:
        add(f'TeamGameLogs_{m}', 'TeamGameLogs', season_nullable=S, measure_type_team_game_logs_nullable=m)
    add('PlayerGameLog', 'PlayerGameLog', player_id=JOKIC, season=S)
    add('TeamGameLog', 'TeamGameLog', team_id=DEN, season=S)
    add('LeagueGameFinder', 'LeagueGameFinder', team_id_nullable=DEN, season_nullable=S, league_id_nullable='00')
    add('PlayerNextNGames', 'PlayerNextNGames', player_id=JOKIC, season_all=S, number_of_games=5)
    add('PlayerNextNGames_2026-27', 'PlayerNextNGames', player_id=JOKIC, season_all='2026-27', number_of_games=5)
    add('ScheduleLeagueV2', 'ScheduleLeagueV2', season=S)
    add('ScheduleLeagueV2_2026-27', 'ScheduleLeagueV2', season='2026-27')
    add('ScoreboardV2_today', 'ScoreboardV2', game_date='2026-10-29')
    add('ScoreboardV3_today', 'ScoreboardV3', game_date='2026-10-29')
    # --- league dashboards
    for m in ['Base', 'Advanced', 'Usage', 'Misc', 'Scoring', 'Defense', 'Four Factors']:
        add(f'LeagueDashPlayerStats_{m}', 'LeagueDashPlayerStats', season=S, measure_type_detailed_defense=m, per_mode_detailed='Totals')
    add('LeagueDashPlayerStats_Base_Last10', 'LeagueDashPlayerStats', season=S, last_n_games=10, per_mode_detailed='PerGame')
    add('LeagueDashPlayerStats_Base_Starters', 'LeagueDashPlayerStats', season=S, starter_bench_nullable='Starters', per_mode_detailed='PerGame')
    add('LeagueDashPlayerStats_Base_Home', 'LeagueDashPlayerStats', season=S, location_nullable='Home', per_mode_detailed='PerGame')
    add('LeagueDashPlayerStats_Base_vsOpp', 'LeagueDashPlayerStats', season=S, vs_team_id_nullable=1610612747, per_mode_detailed='PerGame')
    for m in ['Base', 'Advanced', 'Four Factors', 'Misc', 'Scoring', 'Opponent', 'Defense']:
        add(f'LeagueDashTeamStats_{m}', 'LeagueDashTeamStats', season=S, measure_type_detailed_defense=m, per_mode_detailed='Totals')
    for pt in ['SpeedDistance', 'Rebounding', 'Possessions', 'CatchShoot', 'PullUpShot', 'Defense', 'Drives', 'Passing', 'ElbowTouch', 'PostTouch', 'PaintTouch', 'Efficiency']:
        add(f'LeagueDashPtStats_P_{pt}', 'LeagueDashPtStats', season=S, pt_measure_type=pt, player_or_team='Player', per_mode_simple='Totals')
    add('LeagueDashPtStats_T_Passing', 'LeagueDashPtStats', season=S, pt_measure_type='Passing', player_or_team='Team', per_mode_simple='Totals')
    add('LeagueDashPtStats_T_Rebounding', 'LeagueDashPtStats', season=S, pt_measure_type='Rebounding', player_or_team='Team', per_mode_simple='Totals')
    add('LeagueDashPlayerPtShot', 'LeagueDashPlayerPtShot', season=S)
    add('LeagueDashTeamPtShot', 'LeagueDashTeamPtShot', season=S)
    add('LeagueDashOppPtShot', 'LeagueDashOppPtShot', season=S)
    for dc in ['Overall', '3 Pointers', '2 Pointers', 'Less Than 6Ft', 'Less Than 10Ft', 'Greater Than 15Ft']:
        add(f'LeagueDashPtDefend_{dc}', 'LeagueDashPtDefend', season=S, defense_category=dc)
    add('LeagueDashPtTeamDefend', 'LeagueDashPtTeamDefend', season=S, defense_category='Overall')
    add('LeagueDashPlayerShotLocations', 'LeagueDashPlayerShotLocations', season=S)
    add('LeagueDashTeamShotLocations', 'LeagueDashTeamShotLocations', season=S)
    add('LeagueDashPlayerBioStats', 'LeagueDashPlayerBioStats', season=S)
    add('LeagueDashPlayerClutch', 'LeagueDashPlayerClutch', season=S)
    add('LeagueDashTeamClutch', 'LeagueDashTeamClutch', season=S)
    add('LeagueDashLineups_5_Base', 'LeagueDashLineups', season=S, group_quantity=5, measure_type_detailed_defense='Base')
    add('LeagueDashLineups_5_Adv', 'LeagueDashLineups', season=S, group_quantity=5, measure_type_detailed_defense='Advanced')
    add('LeagueDashLineups_2_Base', 'LeagueDashLineups', season=S, group_quantity=2, measure_type_detailed_defense='Base')
    add('LeagueLineupViz', 'LeagueLineupViz', season=S, group_quantity=5, minutes_min=10)
    add('LeagueHustleStatsPlayer', 'LeagueHustleStatsPlayer', season=S)
    add('LeagueHustleStatsTeam', 'LeagueHustleStatsTeam', season=S)
    add('LeaguePlayerOnDetails', 'LeaguePlayerOnDetails', team_id=DEN, season=S)
    add('LeagueSeasonMatchups', 'LeagueSeasonMatchups', season=S, off_player_id_nullable=JOKIC)
    add('MatchupsRollup', 'MatchupsRollup', season=S, def_player_id_nullable=JOKIC)
    for pt in ['Isolation', 'Transition', 'PRBallHandler', 'PRRollman', 'Postup', 'Spotup', 'Handoff', 'Cut', 'OffScreen', 'OffRebound', 'Misc']:
        add(f'SynergyPlayTypes_P_Off_{pt}', 'SynergyPlayTypes', season=S, play_type_nullable=pt, player_or_team_abbreviation='P', type_grouping_nullable='offensive')
    add('SynergyPlayTypes_T_Def_Isolation', 'SynergyPlayTypes', season=S, play_type_nullable='Isolation', player_or_team_abbreviation='T', type_grouping_nullable='defensive')
    add('PlayerEstimatedMetrics', 'PlayerEstimatedMetrics', season=S)
    add('TeamEstimatedMetrics', 'TeamEstimatedMetrics', season=S)
    add('LeagueStandingsV3', 'LeagueStandingsV3', season=S)
    add('LeagueLeaders', 'LeagueLeaders', season=S)
    add('DefenseHub', 'DefenseHub', season=S)
    add('GravityLeaders', 'GravityLeaders', season=S)
    add('HomePageV2', 'HomePageV2', season=S)
    # --- player endpoints
    add('PlayerDashboardByGeneralSplits', 'PlayerDashboardByGeneralSplits', player_id=JOKIC, season=S)
    add('PlayerDashboardByLastNGames', 'PlayerDashboardByLastNGames', player_id=JOKIC, season=S)
    add('PlayerDashboardByGameSplits', 'PlayerDashboardByGameSplits', player_id=JOKIC, season=S)
    add('PlayerDashboardByTeamPerformance', 'PlayerDashboardByTeamPerformance', player_id=JOKIC, season=S)
    add('PlayerDashboardByShootingSplits', 'PlayerDashboardByShootingSplits', player_id=JOKIC, season=S)
    add('PlayerDashboardByClutch', 'PlayerDashboardByClutch', player_id=JOKIC, season=S)
    add('PlayerDashboardByYearOverYear', 'PlayerDashboardByYearOverYear', player_id=JOKIC, season=S)
    add('PlayerDashPtPass', 'PlayerDashPtPass', player_id=JOKIC, team_id=DEN, season=S)
    add('PlayerDashPtReb', 'PlayerDashPtReb', player_id=JOKIC, team_id=DEN, season=S)
    add('PlayerDashPtShots', 'PlayerDashPtShots', player_id=JOKIC, team_id=DEN, season=S)
    add('PlayerDashPtShotDefend', 'PlayerDashPtShotDefend', player_id=JOKIC, team_id=DEN, season=S)
    add('PlayerVsPlayer', 'PlayerVsPlayer', player_id=JOKIC, vs_player_id=LEBRON, season=S)
    add('PlayerCompare', 'PlayerCompare', player_id_list=str(JOKIC), vs_player_id_list=str(LEBRON), season=S)
    add('PlayerCareerStats', 'PlayerCareerStats', player_id=JOKIC)
    add('PlayerProfileV2', 'PlayerProfileV2', player_id=JOKIC)
    add('PlayerFantasyProfileBarGraph', 'PlayerFantasyProfileBarGraph', player_id=JOKIC, season=S)
    add('CommonPlayerInfo', 'CommonPlayerInfo', player_id=JOKIC)
    add('PlayerIndex', 'PlayerIndex', season=S)
    add('CommonAllPlayers', 'CommonAllPlayers', is_only_current_season=0, season=S)
    add('CommonTeamRoster', 'CommonTeamRoster', team_id=DEN, season=S)
    add('ShotChartDetail', 'ShotChartDetail', team_id=0, player_id=JOKIC, season_nullable=S, context_measure_simple='FGA', season_type_all_star='Regular Season')
    add('ShotChartLeagueWide', 'ShotChartLeagueWide', season=S)
    add('InfographicFanDuelPlayer', 'InfographicFanDuelPlayer', game_id=g)
    # --- team endpoints
    add('TeamInfoCommon', 'TeamInfoCommon', team_id=DEN, season_nullable=S)
    add('TeamDetails', 'TeamDetails', team_id=DEN)
    add('TeamDashboardByGeneralSplits', 'TeamDashboardByGeneralSplits', team_id=DEN, season=S)
    add('TeamDashboardByShootingSplits', 'TeamDashboardByShootingSplits', team_id=DEN, season=S)
    add('TeamDashLineups', 'TeamDashLineups', team_id=DEN, season=S, group_quantity=5)
    add('TeamDashPtPass', 'TeamDashPtPass', team_id=DEN, season=S)
    add('TeamDashPtReb', 'TeamDashPtReb', team_id=DEN, season=S)
    add('TeamDashPtShots', 'TeamDashPtShots', team_id=DEN, season=S)
    add('TeamPlayerDashboard', 'TeamPlayerDashboard', team_id=DEN, season=S)
    add('TeamPlayerOnOffSummary', 'TeamPlayerOnOffSummary', team_id=DEN, season=S)
    add('TeamPlayerOnOffDetails', 'TeamPlayerOnOffDetails', team_id=DEN, season=S)
    add('TeamVsPlayer', 'TeamVsPlayer', team_id=DEN, vs_player_id=LEBRON, season=S)
    add('TeamYearByYearStats', 'TeamYearByYearStats', team_id=DEN)
    # --- game-level
    for v in ['V2', 'V3']:
        for b in ['Traditional', 'Advanced', 'Usage', 'Scoring', 'Misc', 'FourFactors']:
            add(f'BoxScore{b}{v}', f'BoxScore{b}{v}', game_id=g)
    add('BoxScorePlayerTrackV3', 'BoxScorePlayerTrackV3', game_id=g)
    add('BoxScoreDefensiveV2', 'BoxScoreDefensiveV2', game_id=g)
    add('BoxScoreHustleV2', 'BoxScoreHustleV2', game_id=g)
    add('HustleStatsBoxScore', 'HustleStatsBoxScore', game_id=g)
    add('BoxScoreMatchupsV3', 'BoxScoreMatchupsV3', game_id=g)
    add('BoxScoreSummaryV2', 'BoxScoreSummaryV2', game_id=g)
    add('BoxScoreSummaryV3', 'BoxScoreSummaryV3', game_id=g)
    add('PlayByPlayV2', 'PlayByPlayV2', game_id=g)
    add('PlayByPlayV3', 'PlayByPlayV3', game_id=g)
    add('GameRotation', 'GameRotation', game_id=g)
    add('WinProbabilityPBP', 'WinProbabilityPBP', game_id=g)
    add('CumeStatsPlayerGames', 'CumeStatsPlayerGames', player_id=JOKIC, season=S)
    # --- live
    add('live_ScoreBoard', 'ScoreBoard')
    add('live_Odds', 'Odds')
    return sp

def history_specs():
    sp = []
    def add(i, c, **kw): sp.append({'id': i, 'cls': c, 'kw': kw})
    for s in ['1946-47', '1983-84', '1995-96', '1996-97', '2003-04', '2012-13', '2013-14', '2015-16', '2024-25']:
        add(f'H_LeagueGameLog_P_{s}', 'LeagueGameLog', season=s, player_or_team_abbreviation='P')
    for s in ['1995-96', '1996-97', '2000-01', '2012-13', '2013-14', '2015-16']:
        add(f'H_LeagueDashPlayerStats_Adv_{s}', 'LeagueDashPlayerStats', season=s, measure_type_detailed_defense='Advanced', per_mode_detailed='Totals')
        add(f'H_LeagueDashPlayerStats_Usage_{s}', 'LeagueDashPlayerStats', season=s, measure_type_detailed_defense='Usage', per_mode_detailed='Totals')
    for s in ['2012-13', '2013-14', '2014-15', '2015-16', '2016-17', '2017-18', '2018-19']:
        add(f'H_PtStats_Possessions_{s}', 'LeagueDashPtStats', season=s, pt_measure_type='Possessions', player_or_team='Player', per_mode_simple='Totals')
        add(f'H_PtStats_Rebounding_{s}', 'LeagueDashPtStats', season=s, pt_measure_type='Rebounding', player_or_team='Player', per_mode_simple='Totals')
        add(f'H_PtStats_Passing_{s}', 'LeagueDashPtStats', season=s, pt_measure_type='Passing', player_or_team='Player', per_mode_simple='Totals')
    for s in ['2014-15', '2015-16', '2016-17', '2017-18']:
        add(f'H_Hustle_{s}', 'LeagueHustleStatsPlayer', season=s)
    for s in ['2013-14', '2014-15', '2015-16']:
        add(f'H_PtDefend_{s}', 'LeagueDashPtDefend', season=s, defense_category='Overall')
    for s in ['2014-15', '2015-16', '2016-17', '2017-18']:
        add(f'H_Synergy_{s}', 'SynergyPlayTypes', season=s, play_type_nullable='Isolation', player_or_team_abbreviation='P', type_grouping_nullable='offensive')
    for s in ['2006-07', '2007-08', '2012-13']:
        add(f'H_LineupsBase_{s}', 'LeagueDashLineups', season=s, group_quantity=5)
    for s in ['2015-16', '2016-17', '2017-18']:
        add(f'H_SeasonMatchups_{s}', 'LeagueSeasonMatchups', season=s, off_player_id_nullable=2544)
    for s in ['1996-97', '2003-04', '2012-13']:
        add(f'H_ShotChart_{s}', 'ShotChartDetail', team_id=0, player_id=2544 if s != '1996-97' else 893, season_nullable=s, context_measure_simple='FGA', season_type_all_star='Regular Season')
    for s in ['2012-13', '2013-14']:
        add(f'H_EstMetrics_{s}', 'PlayerEstimatedMetrics', season=s)
    for gid, tag in [('0029600001', '1996-97'), ('0020300001', '2003-04'), ('0020700001', '2007-08'), ('0021200001', '2012-13'),
                     ('0021300001', '2013-14'), ('0021500001', '2015-16'), ('0021600001', '2016-17'), ('0021900001', '2019-20'), ('0022200001', '2022-23')]:
        for c in ['BoxScoreTraditionalV2', 'BoxScoreAdvancedV2', 'BoxScoreUsageV2', 'BoxScoreScoringV2', 'BoxScoreMiscV2',
                  'BoxScoreHustleV2', 'BoxScoreDefensiveV2', 'BoxScorePlayerTrackV3', 'BoxScoreMatchupsV3', 'PlayByPlayV2', 'PlayByPlayV3', 'GameRotation', 'BoxScoreSummaryV2']:
            add(f'HG_{c}_{tag}', c, game_id=gid)
    return sp

if __name__ == '__main__':
    specs = main_specs() if PHASE == 'main' else history_specs()
    open(f'{OUT}/results_{PHASE}.jsonl', 'w').close()
    with ThreadPoolExecutor(3) as ex:
        list(ex.map(run, specs))
    print('DONE', len(specs))
