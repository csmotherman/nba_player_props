"""Hand-authored stage narratives per prop market (feature IDs are validated against the registry at build time).

Each stage: (title, [feature ids], 'what is happening'). Stage order is the causal order of the pipeline.
The auto-generated mermaid graphs in NBA_FEATURE_DEPENDENCIES.md are derived from the registry dependency lists, not from here.
"""
PIPELINES = {
    'PTS': dict(root='EXP_PTS_DIST', target='LBL_PTS', mvp_fallback='FRM_SHRUNK_RATE (points per minute) x MIN_EXP, with a pace multiplier', stages=[
        ('1. Minutes', ['MIN_ROLL', 'MIN_EWMA', 'MIN_START_RATE', 'USGR_MINUTES_VACANCY', 'BLO_PROB_BLOWOUT', 'CTX_DAYS_REST', 'MIN_EXP'], 'Projected minutes distribution (incl. DNP mass).'),
        ('2. Possessions', ['ENV_EXP_GAME_POSS', 'POS_MATCHUP_PACE_EXP', 'POS_ONCOURT_FACTOR', 'EXP_ONCOURT_POSS'], 'Expected on-court possessions = k x pace x minutes / 48.'),
        ('3. Shot attempts', ['USG_FGA_PER_100POSS', 'ADJ_OPP_ALLOWED_RATE', 'AVL_TEAMMATE_OUT_USAGE', 'EXP_FGA', 'EXP_FTA'], 'Attempts per possession x possessions, adjusted for opponent and teammates.'),
        ('4. Shot-type split', ['TPT_3PA_RATE', 'TPT_OPP_3PA_ALLOWED', 'EXP_3PA'], 'FGA split into 3PA and 2PA.'),
        ('5. Efficiency', ['SHT_FG_PCT_SHRUNK', 'TPT_3P_PCT_SHRUNK', 'EXP_3P_PCT', 'SHT_FT_PCT_SHRUNK'], 'Make probabilities by shot type (shrunk talent).'),
        ('6. Distribution', ['VAR_DISP_FGA', 'EXP_PTS_DIST'], 'Simulate attempts and makes -> points distribution -> P(over/under).')]),
    'REB': dict(root='EXP_REB_DIST', target='LBL_REB', mvp_fallback='EXP_REB_BASELINE = REB%_hat x (MIN/48) x total rebounds expected from ENV_EXP_MISSED_SHOTS (no tracking needed)', stages=[
        ('0. MVP baseline (no tracking)', ['REB_PCT_ROLL', 'EXP_REB_BASELINE'], 'Rate-based projection; the opportunity pipeline below must beat it in ablation.'),
        ('1. Minutes', ['MIN_EXP'], 'Projected minutes.'),
        ('2. Rebound supply', ['ENV_EXP_GAME_POSS', 'REB_AVAILABLE_MISSES_TEAM', 'ENV_EXP_MISSED_SHOTS', 'REB_OPP_OREB_ALLOWED'], 'Expected missed shots of both teams (supply); history reconciles with total rebounds.'),
        ('3. Opportunity share', ['REB_CHANCES_PER_MIN', 'REB_OPP_SHARE_PER_MISS', 'REB_FRONTCOURT_COMPETITION', 'AVL_TEAMMATE_OUT_USAGE'], 'Share of the available misses the player is positioned to contest, given who else is on the floor.'),
        ('4. Rebound chances', ['EXP_REB_CHANCES'], 'Expected chances = misses during his minutes x share.'),
        ('5. Conversion', ['REB_CONVERSION', 'REB_CONVERSION_SHRUNK'], 'Rebounds per chance (shrunk).'),
        ('6. Distribution', ['VAR_DISP_REB', 'EXP_REB_DIST'], 'Negative-binomial rebounds given overdispersed chances (conversion can marginally exceed 1).')]),
    'AST': dict(root='EXP_AST_DIST', target='LBL_AST', mvp_fallback='EXP_AST_BASELINE = AST%_hat x ((MIN/48) x team FGM expected - own FGM expected) (no tracking needed)', stages=[
        ('0. MVP baseline (no tracking)', ['AST_PCT_ROLL', 'EXP_AST_BASELINE'], 'Rate-based projection; the opportunity pipeline below must beat it in ablation.'),
        ('1. Minutes', ['MIN_EXP'], 'Projected minutes.'),
        ('2. Possessions', ['EXP_ONCOURT_POSS'], 'On-court possessions.'),
        ('3. Playmaking opportunities', ['AST_POT_PER_MIN', 'AST_POT_PER_100POSS', 'AST_TEAM_ASSISTED_RATE', 'AST_BALLHANDLER_COMPETITION', 'AST_OPP_ASSISTS_ALLOWED', 'EXP_POT_AST'], 'Potential assists = possessions x potential assists per possession, adjusted for competition and availability.'),
        ('4. Teammate conversion', ['AST_CONVERSION', 'AST_CONVERSION_SHRUNK', 'AST_TEAMMATE_CONVERSION_PROB'], 'Probability a creating pass is converted, given the receivers who are available.'),
        ('5. Distribution', ['VAR_DISP_AST', 'EXP_AST_DIST'], 'Negative-binomial assists given overdispersed potential assists (NOT binomial: AST can exceed POTENTIAL_AST).')]),
    '3PM': dict(root='EXP_3PM_DIST', target='LBL_FG3M', mvp_fallback='TPT_3PA_PER_MIN x MIN_EXP x TPT_3P_PCT_SHRUNK', stages=[
        ('1. Minutes and possessions', ['MIN_EXP', 'EXP_ONCOURT_POSS'], ''),
        ('2. Shot attempts', ['EXP_FGA'], ''),
        ('3. Three-point attempt rate', ['TPT_3PA_RATE', 'TPT_3PA_PER_MIN', 'TPT_OPP_3PA_ALLOWED', 'TPT_CS_3PA_SHARE', 'EXP_3PA'], 'Attempt volume with role and opponent adjustment.'),
        ('4. Make probability', ['TPT_3P_PCT_SHRUNK', 'EXP_3P_PCT'], 'Heavily shrunk; opponent 3P% allowed expected to add little.'),
        ('5. Distribution', ['VAR_DISP_FG3A', 'EXP_3PM_DIST'], 'Compound distribution: NB attempts, binomial makes.')]),
    'STL': dict(root='EXP_STL_DIST', target='LBL_STL', mvp_fallback='STL_RATE x EXP_ONCOURT_POSS', stages=[
        ('1. Minutes and possessions', ['MIN_EXP', 'EXP_ONCOURT_POSS'], ''),
        ('2. Individual propensity', ['STL_RATE', 'STL_DEFLECTIONS_PER_MIN'], 'Steals per 100 opponent possessions; deflections as a higher-count proxy.'),
        ('3. Opponent turnover supply', ['STL_OPP_TOV_RATE'], 'How often the opponent gives the ball away.'),
        ('4. Distribution', ['VAR_DISP_STL', 'EXP_STL_DIST'], 'Zero-heavy count model.')]),
    'BLK': dict(root='EXP_BLK_DIST', target='LBL_BLK', mvp_fallback='BLK_RATE x EXP_ONCOURT_POSS', stages=[
        ('1. Minutes and possessions', ['MIN_EXP', 'EXP_ONCOURT_POSS'], ''),
        ('2. Individual propensity', ['BLK_RATE', 'BLK_RIM_DEFENDED_PER_MIN'], 'Blocks per possession; rim attempts defended as the opportunity measure.'),
        ('3. Opponent shot supply', ['BLK_OPP_RIM_ATTEMPT_RATE', 'BLK_OPP_2PA_ALLOWED'], 'How many blockable shots the opponent takes.'),
        ('4. Distribution', ['VAR_DISP_BLK', 'EXP_BLK_DIST'], 'Zero-heavy count model.')]),
    'TOV': dict(root='EXP_TOV_DIST', target='LBL_TOV', mvp_fallback='TOV_RATE x EXP_ONCOURT_POSS', stages=[
        ('1. Minutes and possessions', ['MIN_EXP', 'EXP_ONCOURT_POSS'], ''),
        ('2. Individual propensity', ['TOV_RATE', 'TOV_PER_USAGE'], 'Turnovers per possession and per usage opportunity.'),
        ('3. Usage change', ['EXP_FGA', 'USGR_POOLED_ELASTICITY'], 'Turnovers move with usage when teammates are absent.'),
        ('4. Opponent pressure', ['TOV_OPP_PRESSURE'], 'Turnovers the opponent forces.'),
        ('5. Distribution', ['VAR_DISP_TOV', 'EXP_TOV_DIST'], 'Count model.')]),
    'COMBO': dict(root='EXP_COMBO_JOINT', target='LBL_PRA', mvp_fallback='sum of component means with an empirical combined variance', stages=[
        ('1. Component distributions', ['EXP_PTS_DIST', 'EXP_REB_BASELINE', 'EXP_AST_BASELINE'], 'Each built by its own pipeline (baselines in the MVP; full opportunity pipelines optional).'),
        ('2. Dependence', ['VAR_STAT_CORR'], 'Fitted on out-of-fold baseline residuals. Shared minutes and pace induce positive correlation; independent convolution understates variance.'),
        ('3. Joint simulation', ['EXP_COMBO_JOINT'], 'Draw minutes and pace once per simulated game; draw all stats conditional on them; sum for PRA/PR/PA/RA/STOCKS.')]),
}
ROOTS = {m: v['root'] for m, v in PIPELINES.items()}
