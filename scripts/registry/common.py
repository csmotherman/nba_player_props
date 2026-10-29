"""Shared helpers and controlled vocabularies for the feature registry source.

Every feature is declared with feat(). The build script turns the collected list into
nba_feature_registry.json, NBA_FEATURE_CATALOG.csv and the HTML explorer.
"""

MARKETS = ['PTS', 'REB', 'AST', '3PM', 'STL', 'BLK', 'TOV', 'COMBO']
CLASSES = ['RAW', 'CALCULATED', 'ENGINEERED', 'EXTERNAL', 'UNVERIFIED']
# temporal_status: where the value sits relative to tip-off of the TARGET game
TEMPORAL = {
    'label': 'Outcome of the target game. Never a feature for that game.',
    'lagged_observed': 'Observed in games completed BEFORE the target game; usable only with a strict as-of cutoff.',
    'pregame_known': 'Known before tip-off without modelling (schedule, venue, rest).',
    'projected': 'Model output computed pregame from lagged/pregame inputs; a forecast, not an observation.',
    'external_pregame': 'Obtained pregame from a non-nba_api source.',
    'unverified': 'Pregame timing or availability not established.',
}
PRIORITY = {
    'P0': 'Minimum viable set - build first',
    'P1': 'High value - build after the MVP baseline works',
    'P2': 'Experimental - include only if ablation shows lift',
    'P3': 'Deferred - needs missing data or unproven reliability',
}
VSTATUS = {
    'formula_verified': 'Formula reproduced against API-provided columns on real data (data/discovery/qc_results.json)',
    'source_verified': 'Source columns observed in a live response; derivation logic is standard but not independently tested',
    'source_verified_untested_logic': 'Source observed live; the derivation/estimation logic is a hypothesis',
    'hypothesis': 'Definition is a modelling proposal; nothing about its value has been tested',
    'unverified_source': 'Source availability, depth or timing is not established',
    'external_unobtained': 'Requires a source we do not have',
}

LEAK = {
    'label': ('High', 'This is the target-game outcome. Using it as a feature for the same game is direct leakage.'),
    'lag': ('Low', 'Safe when computed only from games with GAME_DATE strictly before the target game date; recompute per target date.'),
    'asof_dash': ('Med', 'Season-level LeagueDash*/PlayerDash* endpoints include every game up to "now" unless date_to_nullable = target date minus 1 day is passed (verified honored). Using un-bounded season totals for a past target leaks the future.'),
    'post': ('High', 'Only known after the game ends; usable only as lagged history for later games.'),
    'proj': ('Med', 'Leak-free only if every input is itself as-of the target date. Fit and evaluate with walk-forward splits; never random k-fold across dates.'),
    'sched': ('Low', 'Schedule is fixed before the season; late postponements are rare. Use the schedule snapshot, not post-hoc results.'),
    'ext': ('Med', 'Timestamp every external record; training rows must use the value that was visible at the pregame cutoff, not the closing/final value.'),
    'static': ('Low', 'Slowly-changing attribute; use the value valid on the target date (e.g. team on that date, not current team).'),
}

MISS = {
    'roll': 'Fewer than N prior games -> shrink toward prior-season value, then position/archetype league mean (empirical-Bayes weight n/(n+k)); emit games_in_window as a companion feature.',
    'rookie': 'No prior history (rookies, returning from long absence) -> use archetype or draft-slot mean with maximum shrinkage; add is_low_sample flag.',
    'none': 'Not expected to be missing once the game has been played; a missing row means the player did not appear (see AVL_*).',
    'ext': 'If the external source is unavailable at the cutoff, set to NaN and add a *_missing indicator; do not forward-fill closing values.',
    'tracking': 'Tracking-derived values are zero/absent before 2013-14 and for some games; treat zero-filled pre-2013 rows as missing, not as zero.',
}

HIST = {
    'box': 'Verified: LeagueGameLog returns rows for 1946-47, 1983-84, 1995-96, 1996-97, 2003-04, 2012-13, 2013-14, 2015-16, 2024-25, 2025-26 (2026-27 in progress). STL/BLK/TOV/OREB/FG3A populated from 1983-84 in tested seasons (all null in 1946-47); PLUS_MINUS null before 1996-97. Seasons between samples not individually tested.',
    'advgl': 'Verified for 2025-26 and 2026-27 (PlayerGameLogs/TeamGameLogs). Deeper history of these exact endpoints is UNTESTED; the underlying values are reproducible from box columns for any season where those exist.',
    'derived_box': 'Computable for any season where the required box columns exist (verified populated 1983-84 onward in sampled seasons; PLUS_MINUS only 1996-97+).',
    'trk': 'Verified: LeagueDashPtStats Possessions/Rebounding/Passing return 0 rows for 2012-13 and rows for 2013-14..2018-19 and 2025-26. Other measure types verified for 2025-26 only. BoxScorePlayerTrackV3 values are populated from 2013-14 (all zeros in sampled 1996-97..2012-13 games).',
    'hustle': 'Verified: LeagueHustleStatsPlayer 0 rows in 2014-15, partial (147 players) in 2015-16, full from 2016-17 (485 players). BoxScoreHustleV2 has player rows from 2016-17 in sampled games (team rows only earlier).',
    'v3box': 'Verified: BoxScore{Traditional,Advanced,Usage,Scoring,Misc,FourFactors}V3 return data for sampled games in 1996-97, 2007-08, 2013-14, 2017-18, 2018-19, 2019-20, 2025-26. V2 equivalents are dead (see inventory).',
    'pbp': 'Verified: PlayByPlayV3 returns rows for sampled games in 1996-97, 2003-04, 2007-08, 2012-13, 2013-14, 2015-16, 2016-17, 2019-20, 2022-23, 2025-26. Event-level accuracy for early seasons not audited.',
    'lineups': 'Verified: LeagueDashLineups 0 rows in 2006-07, rows in 2007-08, 2012-13, 2025-26. Every call returned exactly 2000 rows -> probable server-side cap; completeness UNVERIFIED.',
    'matchups': 'Verified: LeagueSeasonMatchups 0 rows for 2015-16 and 2016-17, rows for 2017-18 and 2025-26. BoxScoreMatchupsV3 / BoxScoreDefensiveV2 error for sampled 2016-17 and earlier games, work for 2017-18, 2018-19, 2019-20, 2022-23, 2025-26.',
    'synergy': 'Verified: SynergyPlayTypes rows for 2014-15 through 2017-18 and 2025-26 (2013-14 and earlier UNTESTED).',
    'ptdef': 'Verified: LeagueDashPtDefend rows for 2013-14, 2014-15, 2015-16, 2025-26 (2012-13 UNTESTED).',
    'adv_season': 'Verified: LeagueDashPlayerStats Advanced/Usage 0 rows in 1995-96, rows from 1996-97 (tested 1996-97, 2000-01, 2012-13, 2013-14, 2015-16, 2025-26).',
    'sched': 'Verified: ScheduleLeagueV2 returned 1400 rows for 2025-26 and 1274 for 2026-27 (see qc_results.json for game-type breakdown). Earlier seasons UNTESTED.',
    'roster': 'Verified for 2025-26 and 2026-27 (CommonTeamRoster, PlayerIndex). Historical-season depth UNTESTED.',
    'shotchart': 'Verified: ShotChartDetail rows for sampled players in 1996-97, 2003-04, 2012-13, 2025-26.',
    'ext': 'Not available from nba_api.',
    'estm': 'Verified: PlayerEstimatedMetrics rows for 2012-13, 2013-14, 2025-26 (earlier UNTESTED).',
    'live': 'Live snapshot only (verified 2026-10-29); no history is served.',
}

ALL = []   # filled by feat()
_IDS = set()


def _split(s):
    if not s:
        return []
    return [x.strip() for x in s.replace('\n', ' ').split(';') if x.strip()]


def feat(id, name, domain, cls, temporal, desc, src, cols, formula, deps, grain, hist, pre, leak, miss, rel,
         val, pri, rank, cluster, ablation, vstatus, notes=''):
    """Declare one feature.

    rel:   'PTS:H,3PM:M' (H/M/L; omitted markets = N, not expected to matter)
    rank:  'pv/rel/cost/stab/ovf'  predicted-value H/M/L, reliability H/M/L, collection cost L/M/H,
           stability H/M/L, overfit risk L/M/H  (ALL are hypotheses, not findings)
    leak:  key into LEAK optionally followed by '|extra text'
    """
    assert id not in _IDS, f'duplicate id {id}'
    _IDS.add(id)
    assert cls in CLASSES, (id, cls)
    assert temporal in TEMPORAL, (id, temporal)
    assert pri in PRIORITY, (id, pri)
    assert vstatus in VSTATUS, (id, vstatus)
    k, _, extra = leak.partition('|')
    lvl, ltxt = LEAK[k]
    relv = {m: 'N' for m in MARKETS}
    parts = [p.split(':') for p in rel.split(',') if p.strip()]
    for m, v in parts:   # 'MIN:x' = acts through minutes, so it is the default for every market
        if m == 'MIN':
            assert v in 'HML', (id, m, v)
            relv = {k: v for k in MARKETS}
    for m, v in parts:
        if m != 'MIN':
            assert m in MARKETS and v in 'HML', (id, m, v); relv[m] = v
    pv, rl, cost, stab, ovf = rank.split('/')
    ALL.append(dict(
        id=id, name=name, domain=domain, classification=cls, temporal_status=temporal, description=desc,
        source_endpoints=_split(src), source_columns=_split(cols), formula=formula.strip(),
        dependencies=[d for d in _split(deps) if not d.startswith('?')],
        optional_dependencies=[d[1:] for d in _split(deps) if d.startswith('?')],
        aggregation_level=grain, historical_availability=hist, pregame_availability=pre,
        leakage_risk=lvl, leakage_notes=(ltxt + (' ' + extra if extra else '')),
        missing_data_handling=miss, market_relevance=relv, validation_method=val, priority=pri,
        validation_status=vstatus, hyp_predictive_value=pv, hyp_reliability=rl, hyp_collection_cost=cost,
        hyp_stability=stab, hyp_overfit_risk=ovf, correlation_cluster=cluster, ablation_group=ablation, notes=notes))
