"""Registry feature id -> warehouse columns that implement it (consumed by the registry for implementation status).
A feature is 'implemented' only if EVERY listed column is produced by asof.build and covered by tests."""
PLAYER_STATS = ['pts', 'reb', 'ast', 'fg3a', 'fga']
WINDOWS = (5, 10, 20)

IMPLEMENTED = {
    'MIN_ROLL': [f'min_{s}_l{n}' for n in WINDOWS for s in ('mean', 'std')] + [f'min_median_l{n}' for n in WINDOWS],
    'MIN_EWMA': ['min_ewma_l20'],
    'FRM_ROLL_RATE': [f'{s}_pm_l{n}' for s in PLAYER_STATS for n in WINDOWS],   # PARTIAL: PTS/REB/AST/FG3A/FGA only
    'FRM_PRIOR_SEASON_RATE': [f'prior_{s}_pm' for s in PLAYER_STATS] + ['prior_season_games', 'prior_season_min'],
    'MIN_START_RATE': ['start_rate_l10', 'start_games_covered_l10'],
    'ROLE_TEAM_CHANGE': ['asof_team_id', 'games_with_team_asof', 'team_changes_365d', 'team_changed_vs_last'],
    'POS_TEAM_PACE_ROLL': ['pace_l5', 'pace_l10', 'opp_pace_l10'],
    'POS_TEAM_POSS_ROLL': ['poss_l5', 'poss_l10', 'opp_poss_l10'],
    'POS_TEAM_OFF_RTG_ROLL': ['off_rating_l10', 'opp_off_rating_l10'],
    'POS_TEAM_DEF_RTG_ROLL': ['def_rating_l10', 'opp_def_rating_l10'],
    'CTX_HOME': ['is_home'],
    'CTX_DAYS_REST': ['rest_days', 'opp_rest_days'],
    'CTX_B2B': ['is_back_to_back', 'opp_is_back_to_back'],
}
# features implemented only in part (documented, not hidden)
PARTIAL = {'FRM_ROLL_RATE': 'PTS, REB, AST, FG3A, FGA only (no STL/BLK/TOV/FGM/FTA)', 'MIN_START_RATE': 'only games with V3 box-score coverage'}
