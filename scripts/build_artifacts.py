"""Build every machine-generated artifact from the registry source and the discovery results.

    python scripts/build_artifacts.py

Writes (repo root): nba_feature_registry.json, NBA_FEATURE_CATALOG.csv, NBA_API_ENDPOINT_INVENTORY.csv,
nba_feature_explorer.html, NBA_FEATURE_DEPENDENCIES.md.  Hand-written: NBA_DATA_BLUEPRINT.md, NBA_DATA_GAPS.md.
Refuses to write anything if registry validation reports errors.
"""
import csv, datetime, glob, json, os, re, sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE); sys.path.insert(0, HERE)
import registry
from registry import checks, common
from registry.pipelines import PIPELINES

DISC = os.path.join(ROOT, 'data', 'discovery')
NBA_API_VERSION = '1.12.0'; DISCOVERY_DATE = '2026-10-29'


# ------------------------------------------------------------------ registry + validation
features = registry.finalize()
res = checks.run(features, DISC, os.path.join(DISC, 'qc_results.json'))
for w in res['warnings']:
    print('WARN ', w)
if res['errors']:
    print('\n'.join('ERROR ' + e for e in res['errors'])); sys.exit('registry validation failed - nothing written')
byid = {f['id']: f for f in features}
for m, p in PIPELINES.items():
    for s in p['stages']:
        for i in s[1]:
            assert i in byid, f'pipeline {m}: unknown feature {i}'
    assert p['root'] in byid and p['target'] in byid, m


# ------------------------------------------------------------------ registry JSON + catalog CSV
def blocked(f):
    return f['classification'] in ('EXTERNAL', 'UNVERIFIED')

for f in features:
    f['blocked_by_external_or_unverified'] = blocked(f)

registry_doc = dict(
    meta=dict(generated_at=datetime.date.today().isoformat(), discovery_date=DISCOVERY_DATE, nba_api_version=NBA_API_VERSION,
              feature_count=len(features), schema_version='1.0',
              note='Rankings (hyp_*) and market_relevance are domain-informed HYPOTHESES, not validated findings. '
                   'Regenerate with scripts/build_artifacts.py; edit definitions under scripts/registry/.'),
    vocabularies=dict(markets=common.MARKETS, classifications=common.CLASSES, temporal_status=common.TEMPORAL,
                      priority=common.PRIORITY, validation_status=common.VSTATUS,
                      relevance={'H': 'high', 'M': 'medium', 'L': 'low', 'N': 'not expected to matter'},
                      source_column_syntax='Endpoint[measure_type_or_variant].COLUMN  (nba_api class names)'),
    pipelines={m: dict(root=p['root'], target=p['target'], mvp_fallback=p['mvp_fallback'],
                       stages=[dict(title=s[0], features=s[1], note=s[2]) for s in p['stages']]) for m, p in PIPELINES.items()},
    features=features)
json.dump(registry_doc, open(os.path.join(ROOT, 'nba_feature_registry.json'), 'w'), indent=1, ensure_ascii=False)

cat_cols = ['id', 'name', 'domain', 'classification', 'temporal_status', 'priority', 'validation_status', 'description',
            'source_endpoints', 'source_columns', 'formula', 'dependencies', 'optional_dependencies', 'aggregation_level',
            'historical_availability', 'pregame_availability', 'leakage_risk', 'leakage_notes', 'missing_data_handling',
            'validation_method', 'hyp_predictive_value', 'hyp_reliability', 'hyp_collection_cost', 'hyp_stability',
            'hyp_overfit_risk', 'correlation_cluster', 'ablation_group', 'blocked_by_external_or_unverified', 'notes']
with open(os.path.join(ROOT, 'NBA_FEATURE_CATALOG.csv'), 'w', newline='') as fh:
    w = csv.writer(fh)
    w.writerow(cat_cols + [f'rel_{m}' for m in common.MARKETS])
    for f in features:
        row = [('; '.join(f[c]) if isinstance(f[c], list) else f[c]) for c in cat_cols]
        w.writerow(row + [f['market_relevance'][m] for m in common.MARKETS])


# ------------------------------------------------------------------ endpoint inventory
sigs = json.load(open(os.path.join(DISC, 'library_signatures.json')))
lib_eps = set(sigs)
recs = {}
order = ['results_main.jsonl', 'results_retry.jsonl', 'results_extra.jsonl', 'results_extra2.jsonl', 'results_history.jsonl']
for fn in order:
    for line in open(os.path.join(DISC, fn)):
        r = json.loads(line); r['_file'] = fn
        recs.setdefault(r['id'], []).append(r)
latest = {}
for tid, lst in recs.items():
    ok = [r for r in lst if r.get('ok')]
    latest[tid] = (ok or lst)[-1]

def is_hist(tid): return tid.startswith(('H_', 'HG_', 'XG_'))

# endpoints deprecated per library docstrings (read from site-packages during discovery)
DEPRECATED = {'BoxScoreAdvancedV2': 'deprecated 2026-27', 'BoxScoreUsageV2': 'deprecated', 'BoxScoreScoringV2': 'deprecated', 'BoxScoreMiscV2': 'deprecated',
              'BoxScoreFourFactorsV2': 'deprecated', 'BoxScoreTraditionalV2': 'deprecated 2025-26 (returns rows for older seasons only)',
              'PlayByPlayV2': 'deprecated 2024-25', 'ScoreboardV2': 'known bad line-score data Oct 22-Dec 25 2025; use ScoreboardV3'}

INFO = {  # class -> (historical_conclusion, pregame_usable, as_of_filters, notes)
 'LeagueGameLog': ('Rows verified for 1946-47, 1983-84, 1995-96, 1996-97, 2003-04, 2012-13, 2013-14, 2015-16, 2024-25, 2025-26 and 2026-27 (in progress). STL/BLK/TOV/OREB/FG3A null in 1946-47, populated 1983-84+; PLUS_MINUS null before 1996-97.', 'Lagged only', 'date_from/date_to exist; Regular Season only by default', 'Most reliable single source of per-player-game box scores. ~10.8 rows per team-game: DNP players mostly absent.'),
 'PlayerGameLogs': ('Verified 2025-26 and 2026-27 only; older seasons UNTESTED.', 'Lagged only', 'date_from_nullable/date_to_nullable verified honored (Jan 1-15 2026 -> 2460 rows)', 'Default (no season_type) returns preseason(001), regular(002), all-star(003), playoffs(004), play-in(005) and cup final(006). Measure types Base/Advanced/Misc/Scoring/Usage OK; Four Factors and Defense failed twice with JSONDecodeError.'),
 'TeamGameLogs': ('Verified 2025-26 and 2026-27 only.', 'Lagged only', 'same params as PlayerGameLogs', 'Measure-type parameter is named measure_type_player_game_logs_nullable (same as the player endpoint). Defense measure failed (JSONDecodeError). MIN is 48 per team-game, not 240.'),
 'PlayerGameLog': ('2025-26 only tested.', 'Lagged only', 'season only', 'Single-player log; use league-wide endpoints for bulk.'),
 'TeamGameLog': ('2025-26 only tested.', 'Lagged only', 'season only', ''),
 'LeagueGameFinder': ('2025-26 only tested.', 'Lagged only', 'many filters (88 params)', 'Team-level game finder.'),
 'LeagueDashPlayerStats': ('Advanced/Usage measure: 0 rows 1995-96, rows from 1996-97 (tested 1996-97, 2000-01, 2012-13, 2013-14, 2015-16, 2025-26).', 'Lagged only with date_to', 'date_from/date_to, last_n_games, opponent_team_id, player_position_abbreviation_nullable, starter_bench_nullable, location, period (Q4 verified) all honored; per_mode Per100Possessions honored; pace_adjust="Y" had NO effect.', 'Advanced measure reports MIN as per-game even with per_mode=Totals. Measure "Four Factors" raised KeyError (not valid for this endpoint or not served).'),
 'LeagueDashTeamStats': ('2025-26 tested; date_to and last_n_games honored.', 'Lagged only with date_to', 'date_to, last_n_games, vs_conference honored', 'Opponent measure gives OPP_* totals per team.'),
 'LeagueDashPtStats': ('Possessions/Rebounding/Passing: 0 rows 2012-13; rows 2013-14..2018-19 and 2025-26. Other measures verified 2025-26 only.', 'Lagged only with date_to', 'date_to honored (Passing, Rebounding). SINGLE-DAY WINDOW (date_from=date_to) verified for Passing on 2026-01-15: 201 players, AST matched game log for 100%.', 'Only source found for per-game potential assists and (via windows) per-game rebound chances/touches for any date range.'),
 'LeagueDashPlayerPtShot': ('2025-26 only.', 'Lagged only with date_to', 'many filters', 'Overall shot frequencies; no catch/pull-up split.'),
 'LeagueDashTeamPtShot': ('2025-26 only.', 'Lagged only', '', ''),
 'LeagueDashOppPtShot': ('2025-26 only.', 'Lagged only', '', 'Opponent shot profile allowed.'),
 'LeagueDashPtDefend': ('Rows verified 2013-14, 2014-15, 2015-16, 2025-26 (2012-13 untested).', 'Lagged only with date_to', 'date_to honored', 'Defender-level shots defended by category (Overall, 3 Pointers, 2 Pointers, <6ft, <10ft, >15ft). Column set differs by category.'),
 'LeagueDashPtTeamDefend': ('2025-26 only.', 'Lagged only', '', ''),
 'LeagueDashPlayerShotLocations': ('2025-26 only.', 'Lagged only with date_to', '', 'Two-level column header; flattened here as Zone:Column.'),
 'LeagueDashTeamShotLocations': ('2025-26 only; measure_type_simple=Opponent verified.', 'Lagged only', '', ''),
 'LeagueDashPlayerBioStats': ('2025-26 only.', 'Static attributes', '', 'Height in inches, weight, draft info.'),
 'LeagueDashPlayerClutch': ('2025-26 only.', 'Lagged only', '', ''),
 'LeagueDashTeamClutch': ('2025-26 only.', 'Lagged only', '', ''),
 'LeagueDashLineups': ('0 rows 2006-07; rows 2007-08, 2012-13, 2025-26. EVERY call returned exactly 2000 rows -> probable cap.', 'Lagged only with date_to', 'date_to honored', 'Completeness UNVERIFIED; cross-check with TeamDashLineups per team.'),
 'LeagueLineupViz': ('2025-26 only (2594 rows with minutes_min=10).', 'Lagged only', '', ''),
 'LeagueHustleStatsPlayer': ('0 rows 2014-15; 147 players 2015-16 (partial); 485+ from 2016-17.', 'Lagged only with date_to', 'date_to honored', ''),
 'LeagueHustleStatsTeam': ('2025-26 only.', 'Lagged only', '', ''),
 'LeaguePlayerOnDetails': ('2025-26 only.', 'Lagged only', '', 'Small result (19 rows for one team).'),
 'LeagueSeasonMatchups': ('0 rows 2015-16 and 2016-17; rows 2017-18 and 2025-26.', 'Lagged only', '', 'Offence-player vs defence-player matchup aggregates.'),
 'MatchupsRollup': ('2025-26 only.', 'Lagged only', '', 'Defender time by offensive position.'),
 'SynergyPlayTypes': ('Rows 2014-15..2017-18 and 2025-26 (2013-14 and earlier untested).', 'Prior-season only unless date filters are verified', 'date filters not tested', 'One call per play type and grouping; 11 offensive play types returned data.'),
 'PlayerEstimatedMetrics': ('Rows 2012-13, 2013-14, 2025-26.', 'Lagged only', '', 'Season-level estimated ratings.'),
 'TeamEstimatedMetrics': ('2025-26 only.', 'Lagged only', '', ''),
 'LeagueStandingsV3': ('2025-26 only.', 'Current table only', '', 'No point-in-time snapshots.'),
 'LeagueLeaders': ('2025-26 only.', 'Lagged only', '', ''),
 'DefenseHub': ('FAILED twice (JSONDecodeError: empty body).', 'n/a', '', 'Cause unestablished (endpoint blocked/removed or param mismatch).'),
 'GravityLeaders': ('2025-26 only.', 'Prior-season only', 'none found', 'Season-aggregate gravity scores.'),
 'HomePageV2': ('2025-26 only.', 'n/a', '', 'Leaders widgets; low value.'),
 'PlayerDashboardByGeneralSplits': ('2025-26 only.', 'Lagged only', 'DaysRest, Location, Month, WinsLosses, Starting position splits', 'Season-level splits for a single player.'),
 'PlayerDashboardByLastNGames': ('2025-26 only.', 'Lagged only', '', ''),
 'PlayerDashboardByGameSplits': ('2025-26 only.', 'Lagged only', '', ''),
 'PlayerDashboardByTeamPerformance': ('2025-26 only.', 'Lagged only', '', 'Splits by points scored/allowed/margin.'),
 'PlayerDashboardByShootingSplits': ('2025-26 only.', 'Lagged only', '', ''),
 'PlayerDashboardByClutch': ('2025-26 only.', 'Lagged only', '', ''),
 'PlayerDashboardByYearOverYear': ('2025-26 only.', 'Lagged only', '', ''),
 'PlayerDashPtPass': ('2025-26 only.', 'Lagged only', '', 'Per-teammate pass volume and outcomes (PassesMade / PassesReceived).'),
 'PlayerDashPtReb': ('2025-26 only.', 'Lagged only', '', ''),
 'PlayerDashPtShots': ('2025-26 only.', 'Lagged only', '', 'Defender distance, shot clock, dribbles, touch time.'),
 'PlayerDashPtShotDefend': ('Returned 0 rows (2025-26 test).', 'n/a', '', 'Empty for the tested player; cause unestablished.'),
 'PlayerVsPlayer': ('2025-26 only.', 'Lagged only', '', ''),
 'PlayerCompare': ('2025-26 only.', 'Lagged only', '', ''),
 'PlayerCareerStats': ('Career totals.', 'Lagged only', '', ''),
 'PlayerProfileV2': ('Career profile.', 'Lagged only', '', ''),
 'PlayerFantasyProfileBarGraph': ('Returned 0 rows.', 'n/a', '', ''),
 'PlayerNextNGames': ('Returned 0 rows for 2024-25, 2025-26 and 2026-27 requests.', 'Expected pregame, but EMPTY in every test', '', 'Do not rely on it; use ScheduleLeagueV2.'),
 'CommonPlayerInfo': ('Current player.', 'Static attributes', '', 'Result-set labels from nba_api are misaligned; use column signatures.'),
 'PlayerIndex': ('2025-26 and 2026-27 verified (523 rows for 2026-27).', 'Static attributes', '', ''),
 'CommonAllPlayers': ('2025-26 only.', 'Static', '', ''),
 'CommonTeamRoster': ('2025-26 and 2026-27 verified.', 'Current snapshot', '', 'Includes coaches.'),
 'ShotChartDetail': ('Rows verified for sampled players in 1996-97, 2003-04, 2012-13, 2025-26.', 'Lagged only', '', 'One call per player; shot-level x/y, zone, distance, made flag.'),
 'ShotChartLeagueWide': ('2025-26 only.', 'Static league averages', '', ''),
 'InfographicFanDuelPlayer': ('Completed game only.', 'Postgame', '', 'FanDuel fantasy points; not a prop line.'),
 'TeamInfoCommon': ('2025-26 only.', 'Lagged', '', ''), 'TeamDetails': ('Static.', 'Static', '', ''),
 'TeamDashboardByGeneralSplits': ('2025-26 only.', 'Lagged only', '', ''), 'TeamDashboardByShootingSplits': ('2025-26 only.', 'Lagged only', '', ''),
 'TeamDashLineups': ('2025-26 only.', 'Lagged only', '', 'Per-team lineups; use to check LeagueDashLineups completeness.'),
 'TeamDashPtPass': ('2025-26 only.', 'Lagged only', '', ''), 'TeamDashPtReb': ('2025-26 only.', 'Lagged only', '', ''),
 'TeamDashPtShots': ('FAILED twice (JSONDecodeError).', 'n/a', '', 'Cause unestablished.'),
 'TeamPlayerDashboard': ('2025-26 only.', 'Lagged only', '', ''),
 'TeamPlayerOnOffSummary': ('2025-26 only; date_to honored.', 'Lagged only', 'date_to honored', 'On/off net ratings.'),
 'TeamPlayerOnOffDetails': ('2025-26 only.', 'Lagged only', 'date_to expected', 'On/off box-stat totals.'),
 'TeamVsPlayer': ('2025-26 only.', 'Lagged only', '', ''), 'TeamYearByYearStats': ('Career.', 'Lagged', '', ''),
 'BoxScoreTraditionalV3': ('Verified 1996-97, 2007-08, 2013-14, 2017-18, 2018-19, 2019-20, 2025-26.', 'Postgame (lagged use); BoxScoreSummaryV3 is the pregame-capable sibling', '', 'position is non-null exactly for starters (20/20 sampled games). comment carries DNP reasons.'),
 'BoxScoreAdvancedV3': ('Verified 1996-97 .. 2025-26 (same sample as Traditional).', 'Postgame', '', ''),
 'BoxScoreUsageV3': ('Verified same sample.', 'Postgame', '', ''), 'BoxScoreScoringV3': ('Verified same sample.', 'Postgame', '', ''),
 'BoxScoreMiscV3': ('Verified same sample.', 'Postgame', '', ''), 'BoxScoreFourFactorsV3': ('Verified same sample.', 'Postgame', '', ''),
 'BoxScorePlayerTrackV3': ('Rows returned for every sampled game; values populated 2013-14+ (all zeros in 1996-97, 2003-04, 2007-08, 2012-13 samples).', 'Postgame', '', 'No potential-assist column.'),
 'BoxScoreDefensiveV2': ('Works 2017-18, 2018-19, 2019-20, 2022-23, 2025-26; errors for 2016-17 and earlier.', 'Postgame', '', 'Matchup-minutes based; V2 only.'),
 'BoxScoreHustleV2': ('Team rows only before 2016-17; player rows 2016-17+ in samples.', 'Postgame', '', ''),
 'HustleStatsBoxScore': ('2025-26 only.', 'Postgame', '', ''),
 'BoxScoreMatchupsV3': ('Works 2017-18+ (tested 2017-18, 2018-19, 2019-20, 2022-23, 2025-26); IndexError for 2016-17 and earlier.', 'Postgame', '', ''),
 'BoxScoreSummaryV3': ('Completed 2025-26 game and an unplayed 2026-27 game verified. Older seasons UNTESTED for V3.', 'GameSummary, GameInfo, ArenaInfo, LineScore, LastFiveMeetings, OtherStats returned for an unplayed game about 4.5h before tip. Officials and InactivePlayers were EMPTY at that time.', '', 'Contains InactivePlayers (11 rows) and Officials for completed games.'),
 'BoxScoreSummaryV2': ('Completed 2025-26 game returned GameInfo/GameSummary/InactivePlayers = 0 rows; older seasons return rows.', 'n/a', '', 'Prefer V3.'),
 'PlayByPlayV3': ('Rows for sampled games 1996-97 .. 2025-26. Unplayed game: JSONDecodeError.', 'Postgame', '', 'actionType includes Substitution ("SUB: X FOR Y"), Made/Missed Shot, Rebound, Turnover, Foul, etc.'),
 'GameRotation': ('FAILED for every season tested (JSONDecodeError).', 'n/a', '', 'Official rotation chart unavailable.'),
 'WinProbabilityPBP': ('FAILED (JSONDecodeError) on 2025-26 sample.', 'n/a', '', ''),
 'CumeStatsPlayerGames': ('2025-26 only.', 'Lagged', '', ''),
 'ScoreboardV2': ('Works but documented as unreliable for Oct 22-Dec 25 2025 line scores.', 'Yes (game list)', '', 'Result-set labels misaligned; use ScoreboardV3.'),
 'ScoreboardV3': ('Works for 2026-04-12 and 2026-10-29.', 'Yes - game list and times for today', 'game_date', ''),
 'ScheduleLeagueV2': ('2025-26 (1400 rows) and 2026-27 (1274 rows). Earlier untested.', 'Yes - full-season schedule', 'season', 'Includes preseason/cup ids; derive rest days from it.'),
 'ScoreBoard': ('Live today only.', 'Yes - today\'s games', '', 'nba_api.live; includes pbOdds placeholder.'),
 'Odds': ('Live snapshot only.', 'Yes - current moneyline/spread snapshot', '', '33 games; markets: 2way, spread only; no totals, no player props, no history.'),
 'BoxScore': ('Live box score; failed for the unplayed game.', 'Live only', '', ''),
}
CANDIDATE = {'TeamAndPlayersVsPlayers': 'medium - lineup/with-without splits', 'PlayerGameStreakFinder': 'low', 'TeamGameStreakFinder': 'low', 'CumeStatsPlayer': 'low',
             'ShotChartLineupDetail': 'medium - lineup shot charts', 'AssistTracker': 'low - assist leaders widget', 'FantasyWidget': 'low', 'LeagueDashPlayerClutch': 'low',
             'DunkScoreLeaders': 'none', 'PlayoffPicture': 'low - standings context'}
GENERIC_NONE = ('Draft', 'Franchise', 'Video', 'Awards', 'AllTime', 'GLAlum', 'Leaders', 'Common', 'PlayerCareerByCollege')

tested_rows = []
harness_errors = []
hist_by_class = defaultdict(list)
for tid, r in latest.items():
    cls = checks.resolve_class(tid, r, lib_eps)
    if tid == 'LeagueDashPlayerStats_FourFactors':
        continue   # retry duplicate of 'LeagueDashPlayerStats_Four Factors' (same failure)
    if not r.get('ok') and r.get('error', '').startswith('TypeError'):
        harness_errors.append(tid); continue   # wrong keyword in our own test call, not an endpoint failure
    if is_hist(tid):
        tag = tid.rsplit('_', 1)[-1] if tid.startswith(('HG_', 'XG_')) else tid.rsplit('_', 1)[-1]
        rows = max([v['rows'] for v in r.get('sets', {}).values()] + [0]) if r.get('ok') else None
        hist_by_class[cls].append((tid, tag, rows, r.get('error', '')[:40]))
        continue
    tested_rows.append((tid, cls, r))

def variant_of(tid, cls):
    t = re.sub(r'^(X|Y|live)_', '', tid)
    return t[len(cls):].lstrip('_') if t.startswith(cls) else t

def hist_string(cls, tid):
    out = []
    toks = set(re.split(r'[_ ]', variant_of(tid, cls))) - {''}
    for htid, tag, rows, err in sorted(hist_by_class.get(cls, []), key=lambda x: x[1]):
        hv = set(re.split(r'[_ ]', re.sub(r'^(H|HG|XG)_', '', htid))) - {''}
        generic = {cls, 'Dash', 'PtStats', 'LeagueDashPlayerStats', 'LeagueGameLog', 'P', 'T'}
        key = hv - generic - {tag} - set(re.split(r'-', tag))
        if cls.startswith('LeagueDash') and key and toks and not any(t == k or (min(len(t), len(k)) >= 3 and (t.startswith(k) or k.startswith(t))) for k in key for t in toks):
            continue
        out.append(f'{tag}={"ERR "+err if rows is None else rows}')
    return '; '.join(out)

used = defaultdict(set)
for f in features:
    for sc in f['source_columns']:
        m = checks.SRC_RE.match(sc)
        if m:
            used[(m.group('ep'), m.group('var') or '')].add(f['id'])
    for se in f['source_endpoints']:
        used[(re.sub(r'\[.*\]', '', se).replace(' (nba_api.live)', '').strip(), '')].add(f['id'])

def feature_use(cls, variant):
    ids = set()
    for (ep, var), s in used.items():
        if ep == cls and (not var or var in variant):
            ids |= s
    return sorted(ids)

inv_cols = ['endpoint_class', 'module', 'http_endpoint', 'test_id', 'variant', 'status', 'rows_returned', 'elapsed_s', 'params_used',
            'library_parameters', 'result_sets_rows', 'response_fields', 'rank_columns_omitted', 'historical_coverage_tested',
            'historical_coverage_conclusion', 'pregame_usability', 'as_of_filter_support', 'notes', 'used_by_feature_count', 'used_by_features']
inv = []
tested_classes = set()
for tid, cls, r in sorted(tested_rows, key=lambda x: (x[1], x[0])):
    tested_classes.add(cls)
    sig = sigs.get(cls, {})
    sets = r.get('sets', {})
    fields = []; nrank = 0
    for n, s in sets.items():
        cs = []
        for c in s['columns']:
            m = re.match(r"^\('(.*)', '(.*)'\)$", c); c = ((m.group(1) + ':' + m.group(2)) if (m and m.group(1)) else (m.group(2) if m else c))
            if c.endswith('_RANK'): nrank += 1
            else: cs.append(c)
        fields.append(f'[{n}] ' + ', '.join(cs))
    if r.get('live_keys'):
        fields = ['[json keys] ' + ', '.join(r['live_keys'])]
    maxrows = max([v['rows'] for v in sets.values()] + [0]) if sets else ''
    if r.get('ok'):
        status = 'OK' if (r.get('nonempty') or r.get('live_keys')) else 'OK_EMPTY'
        if cls in DEPRECATED and not r.get('nonempty') and cls != 'ScoreboardV2':
            status = 'DEPRECATED_NO_DATA'
    else:
        status = 'DEPRECATED_NO_DATA' if cls in DEPRECATED and cls != 'ScoreboardV2' else 'FAILED'
    info = INFO.get(cls, ('2025-26 single-season test.', 'Lagged only', '', ''))
    note = info[3] + ((' ' if info[3] else '') + f'Library: {DEPRECATED[cls]}.' if cls in DEPRECATED else '')
    if status == 'FAILED':
        note += f' Error: {r.get("error", "")[:90]}'
        if tid.startswith('X_Pregame') or tid.startswith('X_Live'):
            note += ' Requested for a game that had not been played (about 4.5h before tip): no box score exists yet - expected.'
    variant = variant_of(tid, cls); fu = feature_use(cls, variant)
    inv.append(dict(endpoint_class=cls, module=sig.get('module', ''), http_endpoint=sig.get('endpoint', ''), test_id=tid, variant=variant, status=status,
                    rows_returned=maxrows, elapsed_s=r.get('elapsed_s', ''), params_used=json.dumps(r.get('params_used', {})),
                    library_parameters='; '.join(sig.get('params', {}).keys()), result_sets_rows='; '.join(f'{n}:{s["rows"]}' for n, s in sets.items()),
                    response_fields=' | '.join(fields), rank_columns_omitted=nrank, historical_coverage_tested=hist_string(cls, tid),
                    historical_coverage_conclusion=info[0], pregame_usability=info[1], as_of_filter_support=info[2], notes=note.strip(),
                    used_by_feature_count=len(fu), used_by_features='; '.join(fu)))
for cls in sorted(lib_eps - tested_classes):
    sig = sigs[cls]
    cand = CANDIDATE.get(cls) or ('none' if cls.startswith(GENERIC_NONE) else 'unassessed')
    inv.append(dict(endpoint_class=cls, module=sig['module'], http_endpoint=sig.get('endpoint') or '', test_id='', variant='', status='NOT_TESTED', rows_returned='', elapsed_s='',
                    params_used='', library_parameters='; '.join(sig['params'].keys()), result_sets_rows='', response_fields='(not observed) library result sets: ' + ', '.join(sig.get('expected') or []),
                    rank_columns_omitted='', historical_coverage_tested='', historical_coverage_conclusion='UNVERIFIED', pregame_usability='UNVERIFIED',
                    as_of_filter_support='', notes=f'Not exercised in discovery. Candidate value for props: {cand}.', used_by_feature_count=0, used_by_features=''))
with open(os.path.join(ROOT, 'NBA_API_ENDPOINT_INVENTORY.csv'), 'w', newline='') as fh:
    w = csv.DictWriter(fh, fieldnames=inv_cols); w.writeheader(); w.writerows(inv)


# ------------------------------------------------------------------ explorer
data = json.dumps(dict(meta=registry_doc['meta'], markets=common.MARKETS, features=features), ensure_ascii=False).replace('<', '\\u003c')
tpl = open(os.path.join(HERE, 'explorer_template.html')).read()
open(os.path.join(ROOT, 'nba_feature_explorer.html'), 'w').write(tpl.replace('/*DATA*/', data))


# ------------------------------------------------------------------ dependency document
SHAPE = {'RAW': ('[', ']'), 'CALCULATED': ('(', ')'), 'ENGINEERED': ('([', '])'), 'EXTERNAL': ('{{', '}}'), 'UNVERIFIED': ('[/', '/]')}
def closure(root):
    seen, order = set(), []
    def go(n):
        if n in seen: return
        seen.add(n)
        for d in byid[n]['dependencies'] + byid[n]['optional_dependencies']: go(d)
        order.append(n)
    go(root); return order

def mermaid(root):
    nodes = closure(root); L = ['```mermaid', 'flowchart LR']
    eps = {}
    for n in nodes:
        f = byid[n]; a, b = SHAPE[f['classification']]
        L.append(f'  {n}{a}"{n}<br/>{f["name"].replace(chr(34), "")}"{b}:::{f["temporal_status"]}')
    for n in nodes:
        f = byid[n]
        for d in f['dependencies']: L.append(f'  {d} --> {n}')
        for d in f['optional_dependencies']: L.append(f'  {d} -.-> {n}')
        if not f['dependencies'] and not f['optional_dependencies']:
            for se in f['source_endpoints']:
                e = re.sub(r'\[.*\]', '', se).strip()
                if e in ('n/a',): continue
                eid = 'EP_' + re.sub(r'\W', '_', e); eps[eid] = e
                L.append(f'  {eid} --> {n}')
    for eid, e in eps.items(): L.append(f'  {eid}[("{e}")]:::endpoint')
    L += ['  classDef label fill:#fde2e2,stroke:#a63a3a,color:#400', '  classDef lagged_observed fill:#e8eef7,stroke:#1f5fbf,color:#012',
          '  classDef pregame_known fill:#e2f4e8,stroke:#2f7d4f,color:#031', '  classDef projected fill:#efe5fb,stroke:#8a4fbf,color:#210',
          '  classDef external_pregame fill:#fdebd7,stroke:#b8631a,color:#310', '  classDef unverified fill:#eee,stroke:#888,stroke-dasharray:4 3,color:#222',
          '  classDef endpoint fill:#fff,stroke:#555,color:#111', '```']
    return '\n'.join(L)

md = ['# NBA Feature Dependencies', '',
      f'> Generated by `scripts/build_artifacts.py` from the feature registry (nba_api {NBA_API_VERSION}, discovery {DISCOVERY_DATE}). Do not edit by hand - edit `scripts/registry/` and rebuild.', '',
      '## How to read this', '',
      '* **Temporal status** (node colour) is the key leakage control. Every node is one of:',
      ]
for k, v in common.TEMPORAL.items(): md.append(f'  * `{k}` - {v}')
md += ['* Arrows run from an input to the feature built from it. Solid = required, dashed = optional upgrade.',
       '* Node shape: `[ ]` RAW, `( )` CALCULATED, `([ ])` ENGINEERED, `{{ }}` EXTERNAL, `[/ /]` UNVERIFIED. Cylinders are nba_api endpoints.',
       '* Past-game outcomes (`LBL_*`) appear only as inputs to *lagged* rolling features. The target game\'s own outcome is never an input to a pregame node (enforced by `registry/checks.py`).',
       '* "Projected" nodes are model outputs (forecasts), not observations. A deterministic calculation and a statistical forecast are never labelled the same.', '',
       '## Pipelines by prop market', '']
for m, p in PIPELINES.items():
    md += [f'### {m}  (target: `{p["target"]}`)', '', f'**MVP fallback:** {p["mvp_fallback"]}', '', '**Causal order (before tip-off -> distribution):**', '']
    for title, ids, note in p['stages']:
        names = ', '.join(f'`{i}` ({byid[i]["classification"][0:4]}, {byid[i]["priority"]})' for i in ids) if ids else '(simulation step)'
        md.append(f'* **{title}** {("- " + note) if note else ""}  ')
        md.append(f'  {names}')
    md += ['', '**Known before tip-off** (nodes feeding the root): ' + ', '.join(f'`{n}`' for n in closure(p['root']) if byid[n]['temporal_status'] in ('pregame_known', 'projected', 'external_pregame', 'lagged_observed')) + '.', '',
           f'**Outcome (never an input):** `{p["target"]}` in the target game.', '',
           '<details><summary>Auto-generated dependency graph</summary>', '', mermaid(p['root']), '', '</details>', '']
md += ['## Shared upstream nodes', '', 'Features used by the most pipelines (a change here propagates widely):', '']
cnt = Counter()
for m, p in PIPELINES.items():
    for n in closure(p['root']): cnt[n] += 1
for n, c in cnt.most_common(12): md.append(f'* `{n}` - in {c} of {len(PIPELINES)} pipelines')
md += ['', '## Full dependency table', '', '| Feature | Class | Temporal | Priority | Requires | Optional |', '|---|---|---|---|---|---|']
for f in features:
    if f['dependencies'] or f['optional_dependencies']:
        md.append(f'| `{f["id"]}` | {f["classification"]} | {f["temporal_status"]} | {f["priority"]} | {", ".join(f["dependencies"])} | {", ".join(f["optional_dependencies"])} |')
open(os.path.join(ROOT, 'NBA_FEATURE_DEPENDENCIES.md'), 'w').write('\n'.join(md) + '\n')


# ------------------------------------------------------------------ inject generated tables into the hand-written Blueprint
SCORE = {'H': 3, 'M': 2, 'L': 1}
def score(f):
    return (2 * SCORE[f['hyp_predictive_value']] + SCORE[f['hyp_reliability']] + SCORE[f['hyp_stability']]
            - SCORE[f['hyp_collection_cost']] - SCORE[f['hyp_overfit_risk']])

def table(headers, rows):
    return '\n'.join(['| ' + ' | '.join(headers) + ' |', '|' + '---|' * len(headers)] + ['| ' + ' | '.join(str(c) for c in r) + ' |' for r in rows])

def counts_block():
    ci = Counter(r['status'] for r in inv)
    t = [f'**Registry: {len(features)} features.**', '']
    t.append(table(['Classification', 'Features'], [(k, c) for k, c in Counter(f['classification'] for f in features).most_common()]))
    t.append(''); t.append(table(['Priority', 'Meaning', 'Features'], [(k, common.PRIORITY[k], Counter(f['priority'] for f in features)[k]) for k in sorted(common.PRIORITY)]))
    t.append(''); t.append(table(['Temporal status', 'Features'], [(k, c) for k, c in Counter(f['temporal_status'] for f in features).most_common()]))
    t.append(''); t.append(table(['Validation status', 'Meaning', 'Features'], [(k, common.VSTATUS[k], Counter(f['validation_status'] for f in features)[k]) for k in common.VSTATUS]))
    t.append(''); t.append(f'**Endpoint inventory: {len(inv)} rows** ({len(lib_eps)} library classes; {len(tested_classes)} exercised, {len(lib_eps) - len(tested_classes)} not). Harness errors from my own wrong keyword names are excluded ({len(harness_errors)}).')
    t.append(''); t.append(table(['Test status', 'Rows'], [(k, c) for k, c in ci.most_common()]))
    return '\n'.join(t)

def rankings_block():
    out = []
    for m in common.MARKETS:
        c = [f for f in features if f['market_relevance'][m] in ('H', 'M') and not f['id'].startswith('LBL_')]
        c.sort(key=lambda f: (-(f['market_relevance'][m] == 'H'), -score(f), f['id']))
        rows = [(i + 1, f'`{f["id"]}`' + (' ‡' if blocked(f) or f['classification'] == 'EXTERNAL' else ''), f['classification'], f['priority'], f['market_relevance'][m], score(f), f['temporal_status']) for i, f in enumerate(c[:10])]
        out += [f'**{m}**  (top 10 of {len(c)} candidates with High/Medium relevance; ‡ = external or unverified source)', '', table(['#', 'Feature', 'Class', 'Pri', 'Relevance', 'Score', 'Temporal'], rows), '']
    return '\n'.join(out)

def clusters_block():
    rows = [(k, len(v), ', '.join(f'`{i}`' for i in v)) for k, v in sorted(res['info']['correlation_clusters'].items(), key=lambda kv: -len(kv[1]))]
    return table(['Cluster', 'Size', 'Members'], rows)

def ablation_block():
    g = defaultdict(list)
    for f in features: g[f['ablation_group']].append(f)
    rows = []
    for k, v in sorted(g.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        if len(v) < 2 or k == 'targets': continue
        rows.append((k, len(v), Counter(f['priority'] for f in v).most_common(1)[0][0], ', '.join(f'`{f["id"]}`' for f in v)))
    return table(['Group', 'Size', 'Typical priority', 'Members'], rows)

def mvp_block():
    p0 = [f for f in features if f['priority'] == 'P0']
    core = [f for f in p0 if not f['id'].startswith(('LBL_', 'BOX_'))]
    api_only = [f for f in core if not blocked(f)]
    out = [f'P0 = {len(p0)} features: {len([f for f in p0 if f["id"].startswith("LBL_")])} labels, {len([f for f in p0 if f["id"].startswith("BOX_")])} raw-ingest columns, '
           f'**{len(api_only)} modelled features using nba_api data only**, and {len(core) - len(api_only)} blocked by external data.', '']
    dom = defaultdict(list)
    for f in core: dom[f['domain']].append(f)
    rows = [(d, ', '.join(f'`{f["id"]}`' + (' ‡' if blocked(f) else '') for f in fs)) for d, fs in sorted(dom.items())]
    out.append(table(['Domain', 'P0 features (‡ = needs external data)'], rows))
    return '\n'.join(out)

def inject(path, name, text):
    s = open(path).read()
    a, b = f'<!-- BEGIN:{name} -->', f'<!-- END:{name} -->'
    i, j = s.index(a) + len(a), s.index(b)
    open(path, 'w').write(s[:i] + '\n\n' + text + '\n\n' + s[j:])

BP = os.path.join(ROOT, 'NBA_DATA_BLUEPRINT.md')
if os.path.exists(BP):
    for nm, fn in [('counts', counts_block), ('rankings', rankings_block), ('clusters', clusters_block), ('ablation', ablation_block), ('mvp', mvp_block)]:
        inject(BP, nm, fn())


# ------------------------------------------------------------------ summary
S = dict(features=len(features), by_class=Counter(f['classification'] for f in features), by_priority=Counter(f['priority'] for f in features),
         by_temporal=Counter(f['temporal_status'] for f in features), by_validation=Counter(f['validation_status'] for f in features),
         inventory_rows=len(inv), harness_errors_excluded=harness_errors, inventory_status=Counter(r['status'] for r in inv), library_endpoints=len(lib_eps), tested_classes=len(tested_classes),
         clusters={k: len(v) for k, v in res['info']['correlation_clusters'].items()}, p0_blocked=res['info']['p0_blocked_by_external'])
json.dump(S, open(os.path.join(DISC, 'build_summary.json'), 'w'), indent=1, default=dict)
print(json.dumps(S, indent=1, default=dict))
