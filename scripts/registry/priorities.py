"""Single authority for P0 (minimum viable set). Any feature declared P0 elsewhere but absent here is demoted to P1.

P0 = what is needed to train and evaluate a first accurate model using nba_api data only, plus the externals that
block serving/backtesting (flagged blocked_by_external in the catalog).
"""
P0 = {
    # targets / labels
    'LBL_PTS', 'LBL_REB', 'LBL_AST', 'LBL_FG3M', 'LBL_STL', 'LBL_BLK', 'LBL_TOV', 'LBL_PRA', 'LBL_PR', 'LBL_PA', 'LBL_RA', 'LBL_STOCKS',
    'LBL_FGA', 'LBL_FG3A', 'LBL_MIN',
    # raw ingest
    'BOX_GAME_TYPE', 'BOX_FGM', 'BOX_FGA', 'BOX_FG3M', 'BOX_FG3A', 'BOX_FTM', 'BOX_FTA', 'BOX_OREB', 'BOX_DREB', 'BOX_PF',
    'BOX_USG_PCT', 'BOX_POSS', 'BOX_PACE', 'BOX_AST_PCT', 'BOX_REB_PCT', 'BOX_TM_TOV_PCT', 'BOX_TS_PCT',
    # minutes
    'MIN_ROLL', 'MIN_EWMA', 'MIN_START_FLAG_HIST', 'MIN_START_RATE', 'MIN_EXP',
    # volume / rate
    'USG_ROLL', 'USG_FGA_PER_MIN', 'USG_FGA_PER_100POSS', 'SHT_FG_PCT_SHRUNK', 'TPT_3PA_PER_MIN', 'TPT_3PA_RATE', 'TPT_3P_PCT_SHRUNK',
    'AST_PCT_ROLL', 'AST_PER_100POSS', 'REB_PCT_ROLL', 'STL_RATE', 'BLK_RATE', 'TOV_RATE',
    'FRM_ROLL_RATE', 'FRM_EWMA_RATE', 'FRM_SHRUNK_RATE', 'FRM_PRIOR_SEASON_RATE',
    # team / environment
    'POS_TEAM_PACE_ROLL', 'POS_MATCHUP_PACE_EXP', 'POS_TEAM_OFF_RTG_ROLL', 'POS_TEAM_DEF_RTG_ROLL', 'ADJ_OPP_ALLOWED_RATE',
    'ENV_EXP_GAME_POSS', 'ENV_EXP_MISSED_SHOTS',
    # projections
    'EXP_ONCOURT_POSS', 'EXP_FGA', 'EXP_3PA', 'EXP_3P_PCT', 'EXP_3PM_DIST', 'EXP_PTS_DIST', 'VAR_DISP_PTS', 'VAR_DISP_REB', 'VAR_DISP_AST', 'VAR_DISP_3PM', 'VAR_DISP_STL', 'VAR_DISP_BLK', 'VAR_DISP_TOV', 'VAR_DISP_FGA', 'VAR_DISP_FG3A',
    'EXP_REB_BASELINE', 'EXP_AST_BASELINE', 'EXP_STL_DIST', 'EXP_BLK_DIST', 'EXP_TOV_DIST',
    # context / availability / blowout
    'CTX_HOME', 'CTX_DAYS_REST', 'BLO_PROB_BLOWOUT', 'BLO_HIST_BLOWOUT_MIN_LOSS', 'USGR_MINUTES_VACANCY',
    'AVL_PLAYED_FLAG_HIST', 'AVL_INACTIVE_LIST_HIST', 'ARC_POSITION', 'BLO_RATING_SPREAD_PROXY',
    'REB_AVAILABLE_MISSES_TEAM', 'POS_ONCOURT_FACTOR', 'TPT_OPP_3PA_ALLOWED', 'EXP_FTA', 'SHT_FT_PCT_SHRUNK', 'USG_FTA_RATE',
    # external, blocking
    'AVL_TEAMMATE_OUT_USAGE', 'EXT_INJURY_REPORT', 'EXT_PROP_LINES',
}
