"""Targets, raw box-score features, minutes/rotation, usage, shooting, three-point shooting."""
from .common import feat, HIST, MISS

PRE_LAG = 'Yes - lagged (computed from games completed before tip-off)'
PRE_LBL = 'No - this is the outcome being predicted'
PRE_PROJ = 'Yes - projection built pregame from lagged/pregame inputs'
PRE_EXT = 'Only with an external source'
PRE_UNV = 'Timing unverified'
G = 'player-game'

# ---------------------------------------------------------------- TARGETS
D = 'Targets'
for stat, col, mk in [('PTS', 'PTS', 'PTS'), ('REB', 'REB', 'REB'), ('AST', 'AST', 'AST'), ('FG3M', 'FG3M', '3PM'),
                      ('STL', 'STL', 'STL'), ('BLK', 'BLK', 'BLK'), ('TOV', 'TOV', 'TOV')]:
    feat(f'LBL_{stat}', f'{stat} (target)', D, 'RAW', 'label',
         f'Player {stat} in the target game. Prop-market outcome; also the source of every lagged {stat} feature.',
         'LeagueGameLog; PlayerGameLogs', f'LeagueGameLog.{col}; PlayerGameLogs[Base].{col}', f'{stat} as reported',
         '', G, HIST['box'], PRE_LBL, 'label', MISS['none'], f'{mk}:H',
         'Reconcile LeagueGameLog vs PlayerGameLogs[Base] vs BoxScoreTraditionalV3 on a sample of games.', 'P0', 'H/H/L/H/L',
         f'target_{stat}', 'targets', 'source_verified',
         'Filter PlayerGameLogs by GAME_ID prefix: without season_type it mixes preseason(001), regular(002), all-star(003), playoffs(004), play-in(005), cup final(006) - verified in qc_results.json.')
for k, nm, expr, comps in [('PRA', 'Points+Rebounds+Assists', 'PTS+REB+AST', 'LBL_PTS; LBL_REB; LBL_AST'),
                           ('PR', 'Points+Rebounds', 'PTS+REB', 'LBL_PTS; LBL_REB'),
                           ('PA', 'Points+Assists', 'PTS+AST', 'LBL_PTS; LBL_AST'),
                           ('RA', 'Rebounds+Assists', 'REB+AST', 'LBL_REB; LBL_AST'),
                           ('STOCKS', 'Steals+Blocks', 'STL+BLK', 'LBL_STL; LBL_BLK')]:
    feat(f'LBL_{k}', f'{nm} (target)', D, 'CALCULATED', 'label', f'Combo-market outcome {expr}.', 'LeagueGameLog',
         'LeagueGameLog.' + '; LeagueGameLog.'.join(expr.split('+')), expr, comps, G, HIST['box'], PRE_LBL, 'label',
         MISS['none'], 'COMBO:H', 'Exact sum; unit test against the three components.', 'P0', 'H/H/L/H/L', f'target_{k}', 'targets',
         'source_verified', 'Combo variance is NOT the sum of component variances; component correlations matter (see VAR_STAT_CORR).')
feat('LBL_FGA', 'FGA (auxiliary target)', D, 'RAW', 'label', 'Field-goal attempts in the target game; intermediate target for the points/threes pipelines.',
     'LeagueGameLog', 'LeagueGameLog.FGA', 'FGA', '', G, HIST['box'], PRE_LBL, 'label', MISS['none'], 'PTS:H,3PM:M,COMBO:M',
     'Used to train opportunity sub-models (volume x efficiency decomposition).', 'P0', 'H/H/L/H/L', 'aux_targets', 'targets', 'source_verified')
feat('LBL_FG3A', 'FG3A (auxiliary target)', D, 'RAW', 'label', 'Three-point attempts in the target game.', 'LeagueGameLog', 'LeagueGameLog.FG3A', 'FG3A', '',
     G, HIST['box'], PRE_LBL, 'label', MISS['none'], '3PM:H,PTS:M,COMBO:M', 'Auxiliary target for the 3PM volume model.', 'P0', 'H/H/L/H/L', 'aux_targets', 'targets', 'source_verified')
feat('LBL_MIN', 'Minutes (auxiliary target)', D, 'RAW', 'label',
     'Minutes played in the target game as a decimal (MIN) - MIN_SEC string gives second-level precision (matches to <=0.01 min, verified).',
     'LeagueGameLog; PlayerGameLogs', 'LeagueGameLog.MIN; PlayerGameLogs[Base].MIN; PlayerGameLogs[Base].MIN_SEC', 'MIN (decimal minutes)', '', G, HIST['box'],
     PRE_LBL, 'label', MISS['none'], 'PTS:H,REB:H,AST:H,3PM:H,STL:H,BLK:H,TOV:H,COMBO:H',
     'Primary target of the minutes sub-model; evaluate with pinball loss on quantiles.', 'P0', 'H/H/L/H/L', 'aux_targets', 'targets', 'source_verified')

# ---------------------------------------------------------------- BOX (observed, lagged use)
D = 'Player box scores'
box_raw = [('FGM', 'Field goals made'), ('FGA', 'Field goal attempts'), ('FG3M', '3-pointers made'), ('FG3A', '3-pointer attempts'),
           ('FTM', 'Free throws made'), ('FTA', 'Free throw attempts'), ('OREB', 'Offensive rebounds'), ('DREB', 'Defensive rebounds'),
           ('PF', 'Personal fouls'), ('PFD', 'Personal fouls drawn (PlayerGameLogs only)'), ('BLKA', 'Shots blocked (against the player; PlayerGameLogs only)'),
           ('PLUS_MINUS', 'Plus/minus')]
for col, nm in box_raw:
    src = 'PlayerGameLogs' if col in ('PFD', 'BLKA') else 'LeagueGameLog; PlayerGameLogs'
    cols = f'PlayerGameLogs[Base].{col}' if col in ('PFD', 'BLKA') else f'LeagueGameLog.{col}; PlayerGameLogs[Base].{col}'
    hist = HIST['advgl'] if col in ('PFD', 'BLKA') else HIST['box']
    rel = {'FGA': 'PTS:H,3PM:M,COMBO:M', 'FGM': 'PTS:M', 'FG3M': '3PM:H,PTS:M', 'FG3A': '3PM:H,PTS:M', 'FTA': 'PTS:M,COMBO:L', 'FTM': 'PTS:L',
           'OREB': 'REB:M', 'DREB': 'REB:M', 'PF': 'PTS:L,REB:L,AST:L,COMBO:L', 'PFD': 'PTS:L', 'BLKA': 'PTS:L', 'PLUS_MINUS': ''}[col]
    feat(f'BOX_{col}', nm, D, 'RAW', 'lagged_observed', f'{nm} in a completed game. Raw input to every rolling/rate feature; a label only for its own game.',
         src, cols, f'{col} as reported', '', G, hist, PRE_LAG, 'lag', MISS['roll'], rel,
         'Cross-check against BoxScoreTraditionalV3 for a game sample.', 'P0' if col in ('FGM', 'FGA', 'FG3M', 'FG3A', 'FTM', 'FTA', 'OREB', 'DREB', 'PF') else 'P2',
         'M/H/L/H/L', 'box_volume' if col not in ('PLUS_MINUS',) else 'plus_minus', 'box_core', 'source_verified',
         'PLUS_MINUS is a noisy outcome-dependent stat; keep only as an ablation candidate.' if col == 'PLUS_MINUS' else '')
feat('BOX_WL', 'Game result (W/L)', D, 'RAW', 'lagged_observed', 'Win/loss of a completed game.', 'LeagueGameLog', 'LeagueGameLog.WL', 'WL', '', G, HIST['box'],
     PRE_LAG, 'lag', MISS['none'], '', 'n/a', 'P3', 'L/H/L/H/L', 'result', 'box_core', 'source_verified',
     'Almost no direct value for props; used to build team form.')
feat('BOX_GAME_TYPE', 'Game type from GAME_ID prefix', D, 'CALCULATED', 'pregame_known',
     'Season-type flag decoded from the 3-digit GAME_ID prefix (001 preseason, 002 regular, 003 all-star, 004 playoffs, 005 play-in, 006 cup final). Required to avoid contaminating training data.',
     'PlayerGameLogs; ScheduleLeagueV2', 'PlayerGameLogs[Base].GAME_ID; ScheduleLeagueV2.gameId', 'prefix = GAME_ID[0:3] (keep GAME_ID as a zero-padded STRING)', '',
     'game', 'Verified prefixes in 2025-26 PlayerGameLogs: 001, 002, 003, 004, 005, 006 (counts in qc_results.json).', 'Yes - schedule', 'sched', MISS['none'],
     'PTS:M,REB:M,AST:M,3PM:M,STL:M,BLK:M,TOV:M,COMBO:M', 'Assert prefix distribution on each ingest.', 'P0', 'M/H/L/H/L', 'context', 'context_core',
     'source_verified', 'Reading GAME_ID as an integer drops the leading zeros and breaks joins - this actually happened during discovery.')

# advanced per-game (API computed)
adv = [('USG_PCT', 'Usage rate (game)', 'Share of team possessions used while on court (fraction scale 0-1 in PlayerGameLogs).', 'USG', 'PTS:H,AST:M,TOV:H,3PM:M,COMBO:M'),
       ('TS_PCT', 'True shooting % (game)', 'Points per scoring attempt: PTS/(2*(FGA+0.44*FTA)).', 'EFF', 'PTS:M'),
       ('EFG_PCT', 'Effective FG % (game)', '(FGM+0.5*FG3M)/FGA.', 'EFF', 'PTS:M,3PM:L'),
       ('AST_PCT', 'Assist % (game)', 'Share of teammate FGM assisted while on court.', 'AST_RATE', 'AST:H'),
       ('REB_PCT', 'Rebound % (game)', 'Share of available rebounds grabbed while on court.', 'REB_RATE', 'REB:H'),
       ('OREB_PCT', 'Offensive rebound % (game)', 'Share of available offensive rebounds grabbed while on court.', 'REB_RATE', 'REB:M'),
       ('DREB_PCT', 'Defensive rebound % (game)', 'Share of available defensive rebounds grabbed while on court.', 'REB_RATE', 'REB:M'),
       ('TM_TOV_PCT', 'Turnover ratio (game)', 'API name is misleading: it approximates 100*TOV/(FGA+0.44*FTA+AST+TOV), an approximation and NOT an exact identity (data/discovery/formula_checks.json, tm_tov_pct_api_definition); scale 0-100.', 'TOV_RATE', 'TOV:H'),
       ('PACE', 'On-court pace (game)', 'Team possessions per 48 min while this player was on the floor.', 'PACE', 'PTS:M,REB:M,AST:M,3PM:M,COMBO:M'),
       ('POSS', 'On-court possessions (game)', 'Integer possessions while on court. POSS ~ PACE*MIN/48 holds only approximately, outside the integer-rounding bound (formula_checks.json, player_poss_vs_oncourt_pace).', 'PACE', 'PTS:M,REB:M,AST:M,STL:M,BLK:M,TOV:M,COMBO:M'),
       ('PIE', 'Player impact estimate (game)', 'Share of game events contributed; noisy single-game number.', 'impact', ''),
       ('OFF_RATING', 'Offensive rating (game)', 'Team points per 100 possessions while on court.', 'rating', ''),
       ('DEF_RATING', 'Defensive rating (game)', 'Opponent points per 100 possessions while on court.', 'rating', '')]
for col, nm, d, cl, rel in adv:
    feat(f'BOX_{col}', nm, D, 'RAW', 'lagged_observed', d + ' API-computed; one row per player-game.', 'PlayerGameLogs',
         f'PlayerGameLogs[Advanced].{col}', f'{col} as reported', '', G, HIST['advgl'], PRE_LAG, 'lag', MISS['roll'], rel,
         'Re-derive from box columns where a formula exists (qc_checks.py) and compare.', 'P0' if col in ('USG_PCT', 'AST_PCT', 'REB_PCT', 'TM_TOV_PCT', 'POSS', 'PACE', 'TS_PCT') else 'P2',
         'M/H/L/M/L', cl, 'api_advanced', 'source_verified' if col in ('USG_PCT', 'TS_PCT', 'AST_PCT', 'REB_PCT', 'OREB_PCT', 'DREB_PCT', 'TM_TOV_PCT', 'POSS') else 'source_verified')
for col, nm, rel in [('PCT_FGA', 'Share of team FGA while on court', 'PTS:H,3PM:M'), ('PCT_FG3A', 'Share of team 3PA while on court', '3PM:H'),
                     ('PCT_AST', 'Share of team assists while on court', 'AST:H'), ('PCT_REB', 'Share of team rebounds while on court', 'REB:H'),
                     ('PCT_TOV', 'Share of team turnovers while on court', 'TOV:H'), ('PCT_STL', 'Share of team steals while on court', 'STL:H'),
                     ('PCT_BLK', 'Share of team blocks while on court', 'BLK:H'), ('PCT_PTS', 'Share of team points while on court', 'PTS:H')]:
    feat(f'BOX_{col}', nm + ' (game)', D, 'RAW', 'lagged_observed', nm + '. Usage-measure column; bounded 0-1, comparable across pace environments.', 'PlayerGameLogs',
         f'PlayerGameLogs[Usage].{col}', f'{col} as reported', '', G, HIST['advgl'], PRE_LAG, 'lag', MISS['roll'], rel,
         'Check team-level sum of shares ~= 1 per game for shares across players weighted by minutes.', 'P1', 'M/H/L/M/L', 'usage_shares', 'usage_shares', 'source_verified')
for col, nm, rel in [('PCT_FGA_3PT', 'Share of own FGA that are 3s', '3PM:H,PTS:M'), ('PCT_AST_FGM', 'Share of own FGM that were assisted', 'PTS:M,3PM:M,AST:L'),
                     ('PCT_PTS_PAINT', 'Share of own points in the paint', 'PTS:L'), ('PCT_PTS_FB', 'Share of own points on the fast break', 'PTS:L'),
                     ('PCT_UAST_3PM', 'Share of own 3PM unassisted', '3PM:L')]:
    feat(f'BOX_{col}', nm + ' (game)', D, 'RAW', 'lagged_observed', nm + '.', 'PlayerGameLogs', f'PlayerGameLogs[Scoring].{col}', f'{col} as reported', '', G,
         HIST['advgl'], PRE_LAG, 'lag', MISS['roll'], rel, 'Sanity-check bounds [0,1].', 'P1' if col in ('PCT_FGA_3PT', 'PCT_AST_FGM') else 'P2', 'M/H/L/M/M',
         'shot_mix', 'scoring_mix', 'source_verified')

# ---------------------------------------------------------------- MINUTES & ROTATION
D = 'Minutes and rotation'
feat('MIN_ROLL', 'Rolling minutes (mean/median/std)', D, 'CALCULATED', 'lagged_observed',
     'Rolling mean, median and standard deviation of minutes over the last N completed games (N in {3,5,10,20}) plus season-to-date.',
     'LeagueGameLog', 'LeagueGameLog.MIN', 'mean_N = (1/N) * sum_{k=1..N} MIN_{t-k}; same for median and sample std. t = target game; only games with date < date_t.',
     'LBL_MIN', G, HIST['derived_box'], PRE_LAG, 'lag', MISS['roll'] + ' Exclude games the player left early injured when estimating the typical role (flag via MIN < 0.5*median and PF<5).',
     'PTS:H,REB:H,AST:H,3PM:H,STL:H,BLK:H,TOV:H,COMBO:H',
     'Walk-forward MAE of minutes forecast vs naive previous-game and season-mean baselines.', 'P0', 'H/H/L/H/L', 'minutes_history', 'minutes_core', 'source_verified',
     'Single most important input: every counting-stat market scales with minutes.')
feat('MIN_EWMA', 'Exponentially weighted minutes', D, 'CALCULATED', 'lagged_observed',
     'Exponentially weighted moving average of minutes; reacts faster than a window mean to role changes.',
     'LeagueGameLog', 'LeagueGameLog.MIN', 'ewma_t = alpha*MIN_{t-1} + (1-alpha)*ewma_{t-1}; alpha from half-life h games: alpha = 1-0.5^(1/h); h in {3,6,12} are tuned parameters, not known values.',
     'LBL_MIN', G, HIST['derived_box'], PRE_LAG, 'lag', MISS['roll'], 'PTS:H,REB:H,AST:H,3PM:H,STL:H,BLK:H,TOV:H,COMBO:H',
     'Tune h by walk-forward minutes MAE; compare with MIN_ROLL in ablation.', 'P0', 'H/H/L/M/M', 'minutes_history', 'minutes_core', 'source_verified')
feat('MIN_START_FLAG_HIST', 'Starter flag in completed games', D, 'CALCULATED', 'lagged_observed',
     'Whether the player started a past game. BoxScoreTraditionalV3.position is non-empty for exactly the five starters (verified: 20/20 sampled games had exactly 5 per team).',
     'BoxScoreTraditionalV3', 'BoxScoreTraditionalV3.position; BoxScoreTraditionalV3.personId; BoxScoreTraditionalV3.gameId',
     'started = 1 if position is non-null and non-empty else 0 (per player per game). One API call per game.', '', G,
     HIST['v3box'] + ' Starter-flag logic verified on 20 sampled 2025-26 games only.', PRE_LAG, 'lag', MISS['none'],
     'PTS:H,REB:H,AST:H,3PM:H,STL:M,BLK:M,TOV:H,COMBO:H', 'Starter flag vs PlayerDashboardByGeneralSplits.StartingPosition games count per player (season totals).',
     'P0', 'H/H/M/H/L', 'starter', 'minutes_core', 'source_verified',
     'Cost: ~1,230 calls per season. Alternative cheaper path: LeagueDashPlayerStats(starter_bench_nullable="Starters") with single-day windows is UNVERIFIED.')
feat('MIN_START_RATE', 'Starter rate over last N games', D, 'CALCULATED', 'lagged_observed', 'Fraction of last N appearances that were starts.', 'BoxScoreTraditionalV3',
     'BoxScoreTraditionalV3.position', 'start_rate_N = sum(started_{t-k})/N over last N games the player appeared in; N in {5,10}.', 'MIN_START_FLAG_HIST', G,
     HIST['v3box'], PRE_LAG, 'lag', MISS['roll'], 'PTS:H,REB:H,AST:H,3PM:H,TOV:H,COMBO:H', 'Compare against known role changes.', 'P0', 'H/H/M/H/L', 'starter', 'minutes_core', 'source_verified')
feat('MIN_START_PROB_TODAY', 'Probability of starting today', D, 'ENGINEERED', 'projected',
     'Pregame probability the player starts: logistic model over start history, injury/availability of teammates, rest, and (when obtainable) confirmed starters.',
     'BoxScoreTraditionalV3', 'BoxScoreTraditionalV3.position', 'P(start) = logistic(w . [start_rate_5, start_rate_10, teammate_out_flags, rest, ...]); weights are learned. Overridden to 0/1 when external confirmed starters exist (EXT_CONFIRMED_STARTERS).',
     'MIN_START_RATE; AVL_TEAMMATE_OUT_USAGE; EXT_CONFIRMED_STARTERS', G, HIST['v3box'], PRE_PROJ, 'proj', MISS['roll'], 'PTS:H,REB:H,AST:H,3PM:H,TOV:H,COMBO:H',
     'Brier score / log-loss vs start_rate baseline; calibration plot.', 'P1', 'H/M/M/M/M', 'starter', 'minutes_core', 'source_verified_untested_logic')
feat('MIN_EXP', 'Projected minutes (distribution)', D, 'ENGINEERED', 'projected',
     'Pregame distribution of minutes played: mixture of P(DNP/limited) and a continuous component. The single most valuable projected quantity.',
     'LeagueGameLog', 'LeagueGameLog.MIN',
     'Model output, NOT a formula. Inputs: MIN_ROLL, MIN_EWMA, MIN_START_PROB_TODAY, CTX_* rest, BLO_PROB_BLOWOUT, AVL_* teammate availability, MIN_FOUL_TROUBLE_RATE. Recommended: quantile / distributional regression, evaluated on pinball loss.',
     'MIN_ROLL; MIN_EWMA; MIN_START_RATE; CTX_DAYS_REST; BLO_PROB_BLOWOUT; USGR_MINUTES_VACANCY; AVL_TEAMMATE_OUT_USAGE; ?MIN_START_PROB_TODAY; ?MIN_FOUL_TROUBLE_RATE; ?MIN_BACK_TO_BACK_DELTA', G, HIST['derived_box'],
     PRE_PROJ, 'proj', 'If the player may not play (status unknown) keep the DNP mass explicit rather than averaging it into the mean.',
     'PTS:H,REB:H,AST:H,3PM:H,STL:H,BLK:H,TOV:H,COMBO:H', 'Walk-forward pinball loss and coverage; compare with MIN_ROLL-only baseline.', 'P0', 'H/M/M/M/M', 'minutes_projection', 'minutes_core', 'hypothesis')
feat('MIN_FOUL_TROUBLE_RATE', 'Foul-trouble minutes risk', D, 'CALCULATED', 'lagged_observed',
     'Frequency of foul-limited minutes: share of last N games with PF >= 5, and PF per 36 minutes.', 'LeagueGameLog', 'LeagueGameLog.PF; LeagueGameLog.MIN',
     'rate_PF5 = mean(PF_{t-k} >= 5); PF36 = 36 * sum(PF)/sum(MIN) over last N games (N=20).', 'LBL_MIN', G, HIST['derived_box'], PRE_LAG, 'lag', MISS['roll'],
     'PTS:L,REB:M,BLK:M,STL:L,COMBO:L', 'Correlation of PF36 with minutes shortfall vs role baseline.', 'P2', 'L/H/L/M/M', 'fouls', 'minutes_fouls', 'source_verified')
feat('MIN_BACK_TO_BACK_DELTA', 'Minutes change on back-to-backs', D, 'CALCULATED', 'lagged_observed',
     'Player-specific difference in minutes on the second night of a back-to-back vs normal rest.', 'LeagueGameLog', 'LeagueGameLog.MIN; LeagueGameLog.GAME_DATE',
     'delta = mean(MIN | days_rest=0) - mean(MIN | days_rest>=1), shrunk: delta_shrunk = n_b2b/(n_b2b+k) * delta; k tuned.', 'LBL_MIN; CTX_B2B', 'player-season', HIST['derived_box'],
     PRE_LAG, 'lag', 'Fewer than 4 back-to-backs -> use age/position cohort delta.', 'PTS:L,REB:L,AST:L,3PM:L,COMBO:L', 'Does adding it improve minutes MAE on B2B games?', 'P2', 'L/M/L/M/H',
     'rest', 'minutes_rest', 'source_verified_untested_logic')
feat('MIN_RETURN_RAMP', 'Return-from-absence ramp', D, 'CALCULATED', 'lagged_observed',
     'Games since the player returned after missing >= M consecutive team games, and minutes in those games relative to pre-injury baseline.', 'LeagueGameLog; ScheduleLeagueV2',
     'LeagueGameLog.GAME_ID; LeagueGameLog.PLAYER_ID; LeagueGameLog.MIN; ScheduleLeagueV2.gameId',
     'missed = team games (from schedule) with no row for the player and date < t; returned_flag if missed_prev >= M (M=3 tuned); ramp_ratio = MIN_since_return / MIN_median_before_absence.', 'AVL_GAMES_MISSED_STREAK', G,
     HIST['derived_box'], PRE_LAG, 'lag', MISS['rookie'], 'PTS:M,REB:M,AST:M,3PM:M,COMBO:M', 'Event study: minutes in the first 5 games back vs baseline.', 'P1', 'M/M/L/M/M',
     'return', 'minutes_availability', 'source_verified_untested_logic', 'Absence cause (injury vs coach decision vs trade) is not in game logs; BoxScoreSummaryV3.InactivePlayers (historical) helps but is not a reason code.')
feat('MIN_Q4_SHARE', 'Share of minutes in the 4th quarter', D, 'CALCULATED', 'lagged_observed',
     'Fraction of a player\'s minutes played in period 4; high values mean the player is used in close games and low values signal blowout benching.',
     'LeagueDashPlayerStats', 'LeagueDashPlayerStats.MIN; LeagueDashPlayerStats.GP',
     'q4_share = MIN(period=4) / MIN(all periods) from two calls: period=4 (verified honored, 580 rows) and no period filter, both with date_to = t-1.', '', 'player-season (as-of)',
     'Verified for 2025-26 (period=4 returned 580 players). Historical depth UNTESTED.', PRE_LAG, 'asof_dash', MISS['roll'], 'PTS:M,REB:M,AST:M,3PM:M,COMBO:M',
     'Does Q4 share improve blowout-sensitivity modelling beyond BLO_HIST_BLOWOUT_MIN_LOSS?', 'P2', 'M/M/M/M/M', 'blowout', 'minutes_blowout', 'source_verified',
     'Single-day windows (date_from=date_to) are expected to give per-game Q4 minutes but this specific combination is UNTESTED.')
feat('MIN_ROTATION_RECON', 'Reconstructed rotation from play-by-play', D, 'UNVERIFIED', 'unverified',
     'Per-player on-court intervals rebuilt from substitution events. GameRotation (the official rotation chart) failed in every test, so PlayByPlayV3 is the only candidate source.',
     'PlayByPlayV3', 'PlayByPlayV3.actionType; PlayByPlayV3.description; PlayByPlayV3.clock; PlayByPlayV3.period; PlayByPlayV3.personId',
     'Parse actionType="Substitution" rows ("SUB: X FOR Y"); infer period-start lineups from first events; integrate time on court. Accuracy vs box MIN must be checked per game before use.', '',
     'player-game-interval', HIST['pbp'], PRE_LAG, 'lag', 'Games where reconstruction disagrees with box MIN by > 1 min are dropped from on/off-style features.',
     'REB:M,AST:M,PTS:M,COMBO:M', 'Reconcile reconstructed minutes with MIN; require < 1 min error on >95% of player-games.', 'P3', 'M/L/H/M/H', 'rotation', 'rotation_recon', 'unverified_source',
     'Unlocks true on-court lineup features, garbage-time filtering and on-court missed-shot counts. High effort.')

# ---------------------------------------------------------------- USAGE & OPPORTUNITIES
D = 'Usage and offensive opportunities'
feat('USG_ROLL', 'Rolling usage', D, 'CALCULATED', 'lagged_observed', 'Minutes-weighted rolling mean of per-game usage rate over last N games.', 'PlayerGameLogs',
     'PlayerGameLogs[Advanced].USG_PCT; PlayerGameLogs[Base].MIN', 'USG_N = sum(USG_{t-k}*MIN_{t-k}) / sum(MIN_{t-k}) over last N games, N in {5,10,20} + season-to-date.', 'BOX_USG_PCT',
     G, HIST['advgl'], PRE_LAG, 'lag', MISS['roll'], 'PTS:H,AST:M,TOV:H,3PM:M,COMBO:M', 'Walk-forward correlation of USG_N with next-game FGA/min.', 'P0', 'H/H/L/H/L', 'usage', 'usage_core', 'source_verified')
feat('USG_USG_FORMULA', 'Usage from box columns', D, 'CALCULATED', 'lagged_observed',
     'Own usage computation so history can extend beyond the seasons where PlayerGameLogs[Advanced] was verified.', 'PlayerGameLogs; TeamGameLogs',
     'PlayerGameLogs[Base].FGA; PlayerGameLogs[Base].FTA; PlayerGameLogs[Base].TOV; PlayerGameLogs[Base].MIN; TeamGameLogs[Base].FGA; TeamGameLogs[Base].FTA; TeamGameLogs[Base].TOV; TeamGameLogs[Base].MIN',
     'USG = ((FGA + 0.44*FTA + TOV) * TeamMIN_per_player_slot) / (MIN * (TmFGA + 0.44*TmFTA + TmTOV)); TeamMIN_per_player_slot = TeamGameLogs.MIN (48 in regulation; verified that the team MIN column is 48, NOT 240).',
     '', G, HIST['derived_box'], PRE_LAG, 'lag', MISS['none'], 'PTS:M,TOV:M', 'Compared with API USG_PCT on real data: approximate agreement, NOT an identity (formula_checks.json, usg_pct: error and bias recorded).', 'P1', 'M/H/L/H/L', 'usage', 'usage_core', 'source_verified',
     'Residual vs API probably from rounding/tracked minutes; do not mix API and own values within one model.')
feat('USG_FGA_PER_MIN', 'FGA per minute', D, 'CALCULATED', 'lagged_observed', 'Shot-attempt rate per minute on court; pace-agnostic shooting appetite.', 'LeagueGameLog',
     'LeagueGameLog.FGA; LeagueGameLog.MIN', 'rate_N = sum(FGA_{t-k}) / sum(MIN_{t-k}) over last N games; shrunk: (n_min*rate + k*prior)/(n_min+k) with prior = archetype mean.', 'LBL_FGA; LBL_MIN', G,
     HIST['derived_box'], PRE_LAG, 'lag', MISS['roll'], 'PTS:H,3PM:M,COMBO:M', 'Predictive correlation with next-game FGA/min across windows.', 'P0', 'H/H/L/H/L', 'usage', 'usage_core', 'source_verified')
feat('USG_FGA_PER_100POSS', 'FGA per 100 on-court possessions', D, 'CALCULATED', 'lagged_observed',
     'Shot attempts normalised by on-court possessions: removes pace so the rate can be re-scaled to the projected game pace.', 'PlayerGameLogs',
     'PlayerGameLogs[Base].FGA; PlayerGameLogs[Advanced].POSS', 'r = 100 * sum(FGA_{t-k}) / sum(POSS_{t-k}); POSS is the player\'s on-court possession count (integer-rounded by the API).', 'BOX_POSS', G, HIST['advgl'],
     PRE_LAG, 'lag', MISS['roll'], 'PTS:H,3PM:M,COMBO:M', 'Compare with FGA/min as a predictor of next-game FGA after scaling by projected possessions.', 'P0', 'H/H/L/H/L', 'usage', 'usage_core',
     'source_verified', 'Highly collinear with USG_FGA_PER_MIN (cluster usage) - keep one in the final model; test via ablation.')
feat('USG_FTA_RATE', 'Free-throw attempt rate', D, 'CALCULATED', 'lagged_observed', 'FTA per FGA; foul-drawing propensity.', 'LeagueGameLog', 'LeagueGameLog.FTA; LeagueGameLog.FGA',
     'sum(FTA)/sum(FGA) over last N games, shrunk toward archetype mean.', 'LBL_FGA', G, HIST['derived_box'], PRE_LAG, 'lag', MISS['roll'], 'PTS:M,COMBO:L', 'Stability (split-half correlation) across seasons.', 'P1', 'M/H/L/H/L', 'usage', 'shooting_free_throws', 'source_verified')
feat('USG_TOUCHES_PER_MIN', 'Touches per minute', D, 'CALCULATED', 'lagged_observed', 'Ball touches per minute; upstream of usage, assists and turnovers.',
     'BoxScorePlayerTrackV3; LeagueDashPtStats', 'BoxScorePlayerTrackV3.touches; BoxScorePlayerTrackV3.minutes; LeagueDashPtStats[Possessions].TOUCHES; LeagueDashPtStats[Possessions].MIN',
     'touches/min = sum(touches)/sum(minutes) over last N games; per-game from BoxScorePlayerTrackV3 (minutes is "mm:ss" string -> convert).', '', G, HIST['trk'], PRE_LAG, 'lag', MISS['tracking'],
     'PTS:M,AST:H,TOV:H,COMBO:M', 'Does it add lift to AST/TOV models over USG + AST_PCT?', 'P1', 'M/H/M/H/M', 'tracking_touch', 'tracking_touch', 'source_verified')
feat('USG_TIME_OF_POSS', 'Time of possession per minute', D, 'CALCULATED', 'lagged_observed', 'Seconds with the ball per minute on court: measure of ball dominance.',
     'LeagueDashPtStats', 'LeagueDashPtStats[Possessions].TIME_OF_POSS; LeagueDashPtStats[Possessions].MIN; LeagueDashPtStats[Possessions].AVG_SEC_PER_TOUCH; LeagueDashPtStats[Possessions].AVG_DRIB_PER_TOUCH',
     'top_per_min = TIME_OF_POSS / (MIN * GP) from totals with date_to = t-1 (TIME_OF_POSS unit assumed minutes; unit not documented - check against AVG_SEC_PER_TOUCH*TOUCHES/60 before use).', '', 'player-season (as-of)', HIST['trk'], PRE_LAG, 'asof_dash', MISS['tracking'],
     'AST:M,TOV:M,PTS:L', 'Unit check + split-half stability.', 'P2', 'M/M/M/H/M', 'tracking_touch', 'tracking_touch', 'source_verified')
feat('USG_ASSISTED_SHARE', 'Self-creation vs assisted share', D, 'CALCULATED', 'lagged_observed',
     'Rolling share of made FG that were assisted (high = depends on teammates creating shots, so sensitive to teammate absences).', 'PlayerGameLogs',
     'PlayerGameLogs[Scoring].PCT_AST_FGM; PlayerGameLogs[Base].FGM', 'sum(PCT_AST_FGM*FGM)/sum(FGM) over last N games.', 'BOX_PCT_AST_FGM', G, HIST['advgl'], PRE_LAG, 'lag', MISS['roll'], 'PTS:M,3PM:M,AST:L', 'Does interaction with teammate-out flags improve FGA/min forecasts?', 'P2', 'M/M/L/M/M', 'shot_mix', 'scoring_mix', 'source_verified')
feat('USG_COMPETITION_ONCOURT', 'Usage competition from expected teammates', D, 'ENGINEERED', 'projected',
     'Sum of the usage-minutes of the teammates expected to be on court with the player. Captures that the same shots cannot go to everyone.', 'PlayerGameLogs',
     'PlayerGameLogs[Advanced].USG_PCT; PlayerGameLogs[Base].MIN', 'comp_i = sum_{j != i, j expected active} (E[MIN_j]/48) * USG_j^{rolling}; use projected minutes (MIN_EXP) as weights. A modelling proposal; the functional form is not validated.',
     'MIN_EXP; USG_ROLL; AVL_TEAMMATE_OUT_USAGE', G, HIST['advgl'], PRE_PROJ, 'proj', MISS['roll'], 'PTS:M,AST:L,TOV:M,3PM:M,COMBO:M', 'Ablation vs USG_ROLL alone plus teammate-out flags.', 'P2', 'M/M/M/M/H', 'usage', 'usage_redistribution', 'hypothesis')

# ---------------------------------------------------------------- SHOOTING VOLUME & EFFICIENCY
D = 'Shooting volume and efficiency'
feat('SHT_TS_ROLL', 'Rolling true shooting', D, 'CALCULATED', 'lagged_observed', 'Attempt-weighted rolling true-shooting %.', 'LeagueGameLog',
     'LeagueGameLog.PTS; LeagueGameLog.FGA; LeagueGameLog.FTA', 'TS_N = sum(PTS) / (2 * (sum(FGA) + 0.44*sum(FTA))) over last N games (N>=20 recommended; short windows are mostly noise).', 'LBL_PTS; BOX_FGA; BOX_FTA',
     G, HIST['derived_box'], PRE_LAG, 'lag', MISS['roll'], 'PTS:M,COMBO:L', 'Split-half reliability; compare with shrunk estimator.', 'P0', 'M/M/L/M/M', 'efficiency', 'efficiency', 'source_verified',
     'TS reproduces API TS_PCT within the API 3-decimal rounding for all but a handful of rows (formula_checks.json, ts_pct lists the exceptions).')
feat('SHT_FG_PCT_SHRUNK', 'Shrunk FG% (2-point and overall)', D, 'ENGINEERED', 'lagged_observed',
     'Empirical-Bayes estimate of true shooting skill that does not over-react to a hot/cold few games.', 'LeagueGameLog', 'LeagueGameLog.FGM; LeagueGameLog.FGA; LeagueGameLog.FG3M; LeagueGameLog.FG3A',
     'p_hat = (FGM_cum + k*p_prior)/(FGA_cum + k); p_prior = archetype / league mean for the player\'s shot mix; k estimated by beta-binomial MLE (not assumed). Compute separately for 2PT: (FGM-FG3M)/(FGA-FG3A).',
     'USG_FGA_PER_MIN', 'player-season (as-of)', HIST['derived_box'], PRE_LAG, 'lag', MISS['rookie'], 'PTS:M,COMBO:L', 'Out-of-sample log-loss of next-game FG% forecast vs raw rolling and league mean.', 'P0', 'M/M/L/H/L', 'efficiency', 'efficiency', 'source_verified_untested_logic')
feat('SHT_FT_PCT_SHRUNK', 'Shrunk FT%', D, 'ENGINEERED', 'lagged_observed', 'Shrunk free-throw percentage (high skill persistence, small per-game n).', 'LeagueGameLog',
     'LeagueGameLog.FTM; LeagueGameLog.FTA', 'p_hat = (FTM_cum + k*p_prior)/(FTA_cum + k) over multiple seasons; k via beta-binomial MLE.', '', 'player-career (as-of)', HIST['derived_box'], PRE_LAG, 'lag', MISS['rookie'], 'PTS:L', 'Reliability across seasons.', 'P1', 'L/H/L/H/L', 'efficiency', 'shooting_free_throws', 'source_verified_untested_logic')
feat('SHT_ZONE_FREQ', 'Shot-zone frequency profile', D, 'CALCULATED', 'lagged_observed',
     'Share of FGA by zone (restricted area, paint non-RA, mid-range, corner 3, above-break 3) from season-to-date as-of data.', 'LeagueDashPlayerShotLocations',
     'LeagueDashPlayerShotLocations.Restricted Area:FGA; LeagueDashPlayerShotLocations.In The Paint (Non-RA):FGA; LeagueDashPlayerShotLocations.Mid-Range:FGA; LeagueDashPlayerShotLocations.Left Corner 3:FGA; LeagueDashPlayerShotLocations.Right Corner 3:FGA; LeagueDashPlayerShotLocations.Above the Break 3:FGA',
     'freq_z = FGA_z / sum_z FGA_z, z over zones (Backcourt excluded or kept as its own bucket); call with date_to = t-1. Columns are a two-level header.', '', 'player-season (as-of)',
     'Verified 2025-26. Historical depth UNTESTED for this endpoint (ShotChartDetail verified back to 1996-97 as an alternative at higher cost).', PRE_LAG, 'asof_dash', MISS['roll'], 'PTS:M,3PM:M,BLK:L', 'Stability and incremental AUC for 3PA-rate and rim-rate forecasts.', 'P1', 'M/H/M/H/M', 'shot_mix', 'shot_mix', 'source_verified')
feat('SHT_XFG', 'Expected FG% from shot quality', D, 'ENGINEERED', 'lagged_observed',
     'Shot-quality expected FG%: league-average make rate for each shot\'s zone/type applied to the shots the player actually takes. Separates shot selection from shot making.', 'ShotChartDetail',
     'ShotChartDetail.SHOT_ZONE_BASIC; ShotChartDetail.SHOT_ZONE_AREA; ShotChartDetail.SHOT_ZONE_RANGE; ShotChartDetail.SHOT_MADE_FLAG; ShotChartDetail.ACTION_TYPE; ShotChartDetail.SHOT_DISTANCE',
     'xFG = (1/n) * sum_s lg_pct(zone_s, action_s) where lg_pct is a league lookup built from the same as-of window; residual = FG% - xFG measures shot making. ShotChartDetail is per-player (one call each) so cost is high.', '', 'player-season (as-of)', HIST['shotchart'], PRE_LAG, 'lag',
     MISS['rookie'], 'PTS:L,3PM:L', 'Does xFG-based efficiency forecast beat shrunk raw FG%?', 'P3', 'M/M/H/M/M', 'efficiency', 'efficiency', 'source_verified_untested_logic')
feat('SHT_CATCH_SHOOT_SHARE', 'Catch-and-shoot share of attempts', D, 'CALCULATED', 'lagged_observed', 'Share of FGA that are catch-and-shoot vs pull-up; links scoring to teammate creation.',
     'LeagueDashPtStats', 'LeagueDashPtStats[CatchShoot].CATCH_SHOOT_FGA; LeagueDashPtStats[PullUpShot].PULL_UP_FGA; LeagueDashPlayerStats.FGA',
     'cs_share = CATCH_SHOOT_FGA / FGA; pu_share = PULL_UP_FGA / FGA, with date_to = t-1 (windows add up only partially - drives and others exist).', '', 'player-season (as-of)', HIST['trk'], PRE_LAG, 'asof_dash', MISS['tracking'], '3PM:M,PTS:M,AST:L', 'Incremental value for 3PM/3PA models.', 'P2', 'M/H/M/H/M', 'shot_mix', 'shot_mix', 'source_verified')
feat('SHT_OPEN_SHOT_RATE', 'Open/wide-open shot rate', D, 'CALCULATED', 'lagged_observed', 'Share of FGA taken with the closest defender >= 4 ft (open + wide open).', 'PlayerDashPtShots',
     'PlayerDashPtShots.CLOSE_DEF_DIST_RANGE; PlayerDashPtShots.FGA_FREQUENCY; PlayerDashPtShots.FGA', 'open_rate = sum FGA_FREQUENCY over the two largest defender-distance buckets (bucket labels must be read from the response).', '', 'player-season (as-of)', 'Verified 2025-26 only; per-player endpoint.', PRE_LAG, 'asof_dash', MISS['tracking'], '3PM:L,PTS:L', 'Marginal value over SHT_ZONE_FREQ.', 'P3', 'L/M/H/M/H', 'shot_mix', 'shot_mix', 'source_verified')
feat('SHT_DRIVE_RATE', 'Drives per minute', D, 'CALCULATED', 'lagged_observed', 'Drives to the basket per minute: proxy for rim pressure and foul drawing.', 'LeagueDashPtStats',
     'LeagueDashPtStats[Drives].DRIVES; LeagueDashPtStats[Drives].MIN; LeagueDashPtStats[Drives].GP; LeagueDashPtStats[Drives].DRIVE_FGA; LeagueDashPtStats[Drives].DRIVE_PASSES; LeagueDashPtStats[Drives].DRIVE_AST',
     'drives_per_min = DRIVES / (MIN*GP) as-of; drive_fga_share = DRIVE_FGA / DRIVES.', '', 'player-season (as-of)', HIST['trk'], PRE_LAG, 'asof_dash', MISS['tracking'], 'PTS:M,AST:M,TOV:L', 'Incremental lift over USG + FTA rate.', 'P2', 'M/H/M/H/M', 'tracking_touch', 'tracking_touch', 'source_verified')
feat('SHT_PTS_PER_SHOT', 'Points per shooting possession', D, 'CALCULATED', 'lagged_observed', 'PTS/(FGA+0.44*FTA) = 2*TS.', 'LeagueGameLog', 'LeagueGameLog.PTS; LeagueGameLog.FGA; LeagueGameLog.FTA',
     'PTS / (FGA + 0.44*FTA)', 'SHT_TS_ROLL', G, HIST['derived_box'], PRE_LAG, 'lag', MISS['roll'], 'PTS:M', 'Perfectly collinear with SHT_TS_ROLL (2x) - keep one.', 'P3', 'L/H/L/H/L', 'efficiency', 'efficiency', 'source_verified', 'Listed to document the duplicate.')

# ---------------------------------------------------------------- THREE-POINT
D = 'Three-point shooting'
feat('TPT_3PA_PER_MIN', 'Three-point attempts per minute', D, 'CALCULATED', 'lagged_observed', 'Rolling 3PA volume per minute; the dominant driver of 3PM variation.', 'LeagueGameLog',
     'LeagueGameLog.FG3A; LeagueGameLog.MIN', 'sum(FG3A_{t-k})/sum(MIN_{t-k}) over last N games, shrunk toward archetype mean.', 'LBL_FG3A; LBL_MIN', G, HIST['derived_box'], PRE_LAG, 'lag', MISS['roll'], '3PM:H,PTS:M,COMBO:L',
     'Walk-forward correlation with next-game 3PA/min.', 'P0', 'H/H/L/H/L', 'three_volume', 'three_volume', 'source_verified')
feat('TPT_3PA_RATE', 'Three-point attempt rate', D, 'CALCULATED', 'lagged_observed', 'FG3A/FGA; shot-mix measure that is more stable than 3PA/min.', 'LeagueGameLog',
     'LeagueGameLog.FG3A; LeagueGameLog.FGA', 'sum(FG3A)/sum(FGA) over last N games.', 'LBL_FG3A; LBL_FGA', G, HIST['derived_box'], PRE_LAG, 'lag', MISS['roll'], '3PM:H,PTS:M', 'Stability.', 'P0', 'H/H/L/H/L', 'three_volume', 'three_volume', 'source_verified',
     'Collinear with TPT_3PA_PER_MIN and USG_FGA_PER_MIN (3PA/min = 3PA rate x FGA/min) - structure the model as rate x volume to avoid double counting.')
feat('TPT_3P_PCT_SHRUNK', 'Shrunk 3P%', D, 'ENGINEERED', 'lagged_observed', 'Empirical-Bayes estimate of true 3-point shooting talent.', 'LeagueGameLog', 'LeagueGameLog.FG3M; LeagueGameLog.FG3A',
     'p_hat = (FG3M_cum + k*p_prior)/(FG3A_cum + k) across current + prior seasons; p_prior = league mean (or archetype mean); k by beta-binomial MLE. 3P% needs several hundred attempts to stabilise, so k is large.', '', 'player-career (as-of)', HIST['derived_box'], PRE_LAG, 'lag', MISS['rookie'], '3PM:H,PTS:M', 'Out-of-sample log-loss of per-attempt make probability vs raw rolling and league mean.', 'P0', 'H/M/L/H/L', 'three_efficiency', 'three_efficiency', 'source_verified_untested_logic')
feat('TPT_CS_3PA_SHARE', 'Catch-and-shoot share of threes', D, 'CALCULATED', 'lagged_observed', 'Share of 3PA taken off the catch (vs pull-up): dependence on teammates\' creation.', 'LeagueDashPtStats',
     'LeagueDashPtStats[CatchShoot].CATCH_SHOOT_FG3A; LeagueDashPtStats[PullUpShot].PULL_UP_FG3A; LeagueDashPlayerStats.FG3A', 'cs3_share = CATCH_SHOOT_FG3A / FG3A (as-of).', '', 'player-season (as-of)', HIST['trk'], PRE_LAG, 'asof_dash', MISS['tracking'], '3PM:M', 'Ablation vs TPT_3PA_RATE.', 'P2', 'M/H/M/H/M', 'three_volume', 'three_volume', 'source_verified')
feat('TPT_CORNER_SHARE', 'Corner share of threes', D, 'CALCULATED', 'lagged_observed', 'Share of 3PA from the corners (higher % and lower variance).', 'LeagueDashPlayerShotLocations',
     'LeagueDashPlayerShotLocations.Left Corner 3:FGA; LeagueDashPlayerShotLocations.Right Corner 3:FGA; LeagueDashPlayerShotLocations.Above the Break 3:FGA', 'corner_share = (LC3_FGA + RC3_FGA) / (LC3_FGA + RC3_FGA + ATB3_FGA).', '', 'player-season (as-of)', 'Verified 2025-26 only.', PRE_LAG, 'asof_dash', MISS['roll'], '3PM:L', 'Marginal value over shrunk 3P%.', 'P3', 'L/M/M/M/H', 'three_efficiency', 'three_efficiency', 'source_verified')
feat('TPT_OPP_3PA_ALLOWED', 'Opponent 3PA allowed per 100 possessions', D, 'CALCULATED', 'lagged_observed', 'How many threes the opponent lets opponents attempt, pace-normalised.', 'TeamGameLogs',
     'TeamGameLogs[Opponent].OPP_FG3A; TeamGameLogs[Advanced].POSS', '100 * sum(OPP_FG3A) / sum(POSS) over the opponent\'s last N games; shrink toward league mean (n/(n+k)).', 'ADJ_OPP_ALLOWED_RATE', 'team-season (as-of)', HIST['advgl'], PRE_LAG, 'lag', MISS['roll'], '3PM:M,PTS:L', 'Does it add lift beyond player 3PA rate?', 'P1', 'M/M/L/M/M', 'opp_three', 'opp_defense', 'source_verified')
feat('TPT_OPP_3P_PCT_ALLOWED', 'Opponent 3P% allowed (shrunk)', D, 'ENGINEERED', 'lagged_observed', 'Opponent three-point defence, regressed heavily toward the league mean because defensive 3P% allowed is mostly shot luck.', 'TeamGameLogs; LeagueDashPtTeamDefend',
     'TeamGameLogs[Opponent].OPP_FG3M; TeamGameLogs[Opponent].OPP_FG3A; LeagueDashPtTeamDefend.NORMAL_FG_PCT; LeagueDashPtTeamDefend.D_FG_PCT', 'p_hat = (OPP_FG3M_cum + k*lg_3p)/(OPP_FG3A_cum + k); k large (estimated). Shot-quality-adjusted alternative uses LeagueDashPtDefend[3 Pointers].NS_FG3_PCT (expected % of the shots defended).', '', 'team-season (as-of)', HIST['advgl'], PRE_LAG, 'lag', MISS['roll'], '3PM:L', 'Likely near-zero lift; must pass ablation to stay.', 'P2', 'L/M/L/L/H', 'opp_three', 'opp_defense', 'source_verified_untested_logic')
feat('TPT_WIDE_OPEN_RATE', 'Open three rate', D, 'UNVERIFIED', 'unverified', 'Share of the player\'s threes that are open/wide-open (needs defender distance on 3PA only).', 'PlayerDashPtShots', 'PlayerDashPtShots.CLOSE_DEF_DIST_RANGE; PlayerDashPtShots.FG3A', 'Would need FG3A by defender-distance bucket; the verified sets expose FG3A_FREQUENCY/FG3A per bucket, but per-bucket 3PA semantics are not confirmed.', '', 'player-season (as-of)', 'Verified 2025-26 only.', PRE_LAG, 'asof_dash', MISS['tracking'], '3PM:L', 'Check bucket labels and FG3A columns, then compare with SHT_OPEN_SHOT_RATE.', 'P3', 'L/L/H/M/H', 'three_efficiency', 'three_efficiency', 'unverified_source')
