"""Declared NBA-only fallback paths.

A fallback is a DOCUMENTED degraded implementation that runs without the unavailable input. It must (a) name which
inputs it replaces (`for_`; 'SELF' = the feature's own external/unverified input) and (b) say what the degraded
implementation does. Readiness analysis honours ONLY what is declared here; nothing is assumed.
"""
FALLBACKS = {
    'AVL_TEAMMATE_OUT_USAGE': dict(for_=['SELF', 'EXT_INJURY_REPORT'], text='No injury feed: emit NaN plus an `injury_info_missing` indicator; downstream models condition only on lagged availability (AVL_PLAYED_FLAG_HIST, AVL_GAMES_MISSED_STREAK) and cannot react to todays absences. Degraded, executable from nba_api only.'),
    'AVL_OPP_KEY_PLAYER_OUT': dict(for_=['SELF', 'EXT_INJURY_REPORT'], text='Omit (NaN + indicator): opponent availability unknown.'),
    'MIN_START_PROB_TODAY': dict(for_=['EXT_CONFIRMED_STARTERS'], text='History-only start probability from MIN_START_RATE and teammate-availability history; no confirmed lineup.'),
    'CTX_TRAVEL_GEO': dict(for_=['SELF'], text='Omit; use rest days and back-to-back flags only.'),
    'DVP_OPP_RIM_PROTECTION': dict(for_=['AVL_OPP_KEY_PLAYER_OUT'], text='Use the opponent full-season rim-protection average without availability weighting.'),
    'BLO_PROB_BLOWOUT': dict(for_=['BLO_SPREAD_HISTORICAL', 'BLO_SPREAD_LIVE'], text='Use BLO_RATING_SPREAD_PROXY (team-rating spread) as the only spread input.'),
    'MIN_EXP': dict(for_=['MIN_START_PROB_TODAY'], text='Use MIN_START_RATE instead of the start probability; injury information enters only through the degraded AVL_TEAMMATE_OUT_USAGE.'),
    'EXP_3P_PCT': dict(for_=['TPT_CS_3PA_SHARE', 'TPT_OPP_3P_PCT_ALLOWED'], text='p = TPT_3P_PCT_SHRUNK with no shot-type or opponent adjustment.'),
    'FRM_SHRUNK_RATE': dict(for_=['ARC_CLUSTER_ID'], text='Prior = league mean by listed position (ARC_POSITION) instead of cluster mean.'),
    'REB_PCT_ROLL': dict(for_=['BOX_OREB_PCT', 'BOX_DREB_PCT'], text='Use total REB% only.'),
    'EXP_FGA': dict(for_=['USGR_POOLED_ELASTICITY', 'USGR_WITH_WITHOUT'], text='No redistribution term; attempts per possession from USG_FGA_PER_100POSS with opponent factor only.'),
    'EXP_TOV_DIST': dict(for_=['TOV_OPP_PRESSURE', 'USGR_POOLED_ELASTICITY'], text='Player TOV rate x on-court possessions, no opponent-pressure or usage term.'),
    'EXP_STL_DIST': dict(for_=['STL_OPP_TOV_RATE', 'STL_DEFLECTIONS_PER_MIN'], text='STL_RATE x on-court possessions only.'),
    'EXP_BLK_DIST': dict(for_=['BLK_RIM_DEFENDED_PER_MIN', 'BLK_OPP_RIM_ATTEMPT_RATE', 'BLK_OPP_2PA_ALLOWED'], text='BLK_RATE x on-court possessions only.'),
}
